from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar
from .common import _limit_exceeded_response,_meal_type_from_now


@extend_schema(tags=["Diet AI - Patient"])
class DietPhotoUploadUrlView(APIView):
    """Ovqat rasmini DO Spaces'ga yuklash uchun presigned URL."""

    permission_classes = [IsPatient]

    @extend_schema(
        request=PhotoUploadUrlSerializer,
        responses=PhotoUploadUrlSerializer,
        summary="Ovqat rasmi uchun upload URL olish",
        description=(
            "Mobile flow: 1) Bu endpoint dan upload_url + image_key olinadi, "
            "2) PUT {upload_url} bilan fayl S3 ga yuklanadi, "
            "3) POST /diet/analyze-photo/ {image_key} bilan tahlil qilinadi."
        ),
    )
    def post(self, request):
        serializer = PhotoUploadUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_type = serializer.validated_data["file_type"]
        # ext'ni MIME'dan olamiz (loyiha konvensiyasi — file_name'ga ishonmaymiz).
        ext = ext_for_mime(file_type, fallback="jpg")
        unique = uuid.uuid4().hex[:8]
        image_key = f"diet-photos/{request.user.id}/{unique}.{ext}"

        return Response(
            {
                "upload_url": generate_upload_url(image_key, file_type),
                "image_key": image_key,
                "expires_in": 900,
            }
        )


@extend_schema(tags=["Diet AI - Patient"])
class DietAnalyzePhotoView(APIView):
    """Ovqat rasmini Gemini multimodal bilan tahlil qilish."""

    permission_classes = [IsPatient]

    @extend_schema(
        request=AnalyzePhotoSerializer,
        responses=DietMessageSerializer,
        summary="Ovqat rasmini tahlil qilish",
    )
    def post(self, request):
        # 1. Limit
        limit_info = services.check_daily_limit(request.user)
        if not limit_info["allowed"]:
            return _limit_exceeded_response(limit_info)

        serializer = AnalyzePhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1.1 Guardrail: note/food_name matnida xatarli mavzu bo'lsa bloklash
        # (text chat'dagi is_dangerous qoplamasini photo oqimiga ham tatbiq etamiz).
        user_note_text = " ".join(
            str(data.get(field) or "") for field in ("note", "food_name")
        ).strip()
        if user_note_text:
            dangerous, _reason = is_dangerous(user_note_text)
            if dangerous:
                user_lang = (
                    getattr(getattr(request.user, "settings", None), "language", None)
                    or "uz"
                )
                return Response(
                    {"detail": get_safety_response(user_lang)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 2. Conversation topish yoki yaratish
        conv_id = data.get("conversation_id")
        if conv_id:
            try:
                conversation = DietConversation.objects.get(
                    id=conv_id, user=request.user
                )
            except DietConversation.DoesNotExist:
                return Response(
                    {"detail": "Suhbat topilmadi."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            # User preferred til — AI javobi mos tilda kelsin (hardcoded 'uz' emas)
            user_lang = (
                getattr(getattr(request.user, "settings", None), "language", None)
                or "uz"
            )
            conversation = DietConversation.objects.create(
                user=request.user,
                title="Ovqat rasmi tahlili",
                language=user_lang,
            )

        # XAVFSIZLIK: image_key FAQAT o'z prefiksida bo'lsin — aks holda boshqa
        # foydalanuvchi rasmiga kirish (IDOR). Upload diet-photos/{user.id}/ beradi.
        if not str(data["image_key"]).startswith(f"diet-photos/{request.user.id}/"):
            return Response(
                {"detail": "Noto'g'ri image_key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Hajmni S3 metadata orqali OLDIN tekshirish (DoS — katta faylni
        # xotiraga to'liq yuklamasdan rad etish).
        head = head_object_or_none(data["image_key"])
        if head is None:
            return Response(
                {"detail": "Rasm topilmadi yoki yuklab bo'lmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if head["size"] > DIET_MAX_IMAGE_BYTES:
            return Response(
                {"detail": "Rasm hajmi 10 MB dan oshmasligi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3.1 S3 dan rasmni olish
        try:
            image_bytes, image_mime = download_file_bytes(data["image_key"])
        except Exception as e:
            logger.error("Rasmni S3 dan olib bo'lmadi: %s", e)
            return Response(
                {"detail": "Rasm topilmadi yoki yuklab bo'lmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3.2 Yuklab olingach yana bir bor tekshirish (head metadata noto'g'ri bo'lsa)
        if len(image_bytes) > DIET_MAX_IMAGE_BYTES:
            return Response(
                {"detail": "Rasm hajmi 10 MB dan oshmasligi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Foydalanuvchi qo'shimcha ma'lumotlarini birlashtirish
        extra_parts = []
        if data.get("food_name"):
            extra_parts.append(f"Ovqat nomi: {data['food_name']}")
        if data.get("portion"):
            extra_parts.append(f"Porsiya: {data['portion']}")
        if data.get("grams"):
            extra_parts.append(f"Vazn: {data['grams']} gramm")
        if data.get("pieces"):
            extra_parts.append(f"Soni: {data['pieces']} dona")
        if data.get("note"):
            extra_parts.append(f"Eslatma: {data['note']}")

        # Rasm tahlili — APP tilida (mirror emas: rasmda foydalanuvchi matni yo'q,
        # moslashadigan til manbasi yo'q → app tili / X-Language ishlatamiz).
        app_lang = get_request_lang(request)
        photo_prompt = get_photo_analysis_prompt(app_lang)
        if extra_parts:
            photo_prompt += "\n\nFoydalanuvchi qo'shimcha:\n" + "\n".join(extra_parts)

        # 5. Gemini multimodal (saqlashdan oldin — xato bo'lsa yozma qolmasin)
        user_context = services.build_user_context(request.user)
        system_prompt = build_system_prompt(app_lang, user_context, mirror=False)

        result = generate_with_image(
            prompt=photo_prompt,
            image_bytes=image_bytes,
            image_mime_type=image_mime,
            system_instruction=system_prompt,
            response_schema=FOOD_ANALYSIS_SCHEMA,
            max_tokens=8192,
            # Past temperature — bir xil ovqat har safar ~bir xil kaloriya/makro
            # bersin (non-determinizm kamaytiriladi).
            temperature=0.15,
        )

        if "error" in result:
            return Response(
                {"detail": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 6. Structured JSON javobni parse qilish (services helper)
        ai_clean_text, food_data, food_detected = (
            services.parse_food_analysis_response(result["text"] or "")
        )

        # Regression detektori: ovqat topildi, lekin structured food_data bo'sh.
        # FOOD_ANALYSIS_SCHEMA endi food_data'ni majburiy qiladi — bu holat
        # bo'lmasligi kerak. Bo'lsa (model schema'ni buzsa / parse mismatch) — log.
        if food_detected and not food_data:
            logger.warning(
                "Diet analyze-photo: food_detected=true lekin food_data BO'SH "
                "(schema enforcement ishlamadimi?) — text_len=%s",
                len(result["text"] or ""),
            )

        # Gemini food_detected=false qaytargan lekin analysis_markdown bo'sh holat
        if not food_detected and not ai_clean_text:
            ai_clean_text = (
                "Rasmda ovqat ko'rsatilmagan. Iltimos, ovqat rasmini yuklang."
            )

        # 7. user + assistant xabarlarini birga saqlash (atomic)
        user_content = data.get("note") or "Ovqat rasmini tahlil qiling"
        assistant_metadata: dict = {"food_detected": food_detected}
        if food_detected and food_data:
            assistant_metadata["ai_food_data"] = food_data
            assistant_metadata["confirmed"] = False
            # Pro: har-mahal shaxsiy tavsiya (server-side, deterministik).
            # Raqamlar profildan mustaqil (guardrail); faqat matn qoldiqni hisobga oladi.
            if services.has_diet_pro_feature(request.user, "diet_meal_advice"):
                assistant_metadata["meal_advice"] = services.build_meal_advice(
                    request.user,
                    food_data.get("estimated_calories"),
                    food_data.get("glycemic_load"),
                    _meal_type_from_now(),
                )
            else:
                assistant_metadata["meal_advice"] = None

        with transaction.atomic():
            user_msg = DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.USER,
                content=user_content,
                image_key=data["image_key"],
                metadata={
                    "food_name": data.get("food_name") or None,
                    "portion": data.get("portion") or None,
                    "grams": data.get("grams"),
                    "pieces": data.get("pieces"),
                },
            )
            assistant_msg = DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.ASSISTANT,
                content=ai_clean_text,
                metadata=assistant_metadata or None,
                tokens_input=result["tokens_input"],
                tokens_output=result["tokens_output"],
            )
            conversation.save(update_fields=["updated_at"])

        services.increment_usage(
            request.user,
            tokens_input=result["tokens_input"],
            tokens_output=result["tokens_output"],
        )

        return Response(
            {
                "conversation_id": conversation.id,
                "food_detected": food_detected,
                "user_message": DietMessageSerializer(user_msg).data,
                "assistant_message": DietMessageSerializer(assistant_msg).data,
            }
        )


@extend_schema(tags=["Diet AI - Patient"])
class DietAnalyzeTextView(APIView):
    """Ovqatni MATN orqali tahlil qilish — analyze-photo'ning rasmsiz egizagi.

    Foydalanuvchi ovqat nomi + (ixtiyoriy) gramm/porsiya/dona yozadi; AI kaloriya +
    makro + glikemik yukni hisoblaydi. Javob shakli analyze-photo bilan AYNAN bir xil
    (user_message + assistant_message, metadata'da ai_food_data + confirmed=false),
    shuning uchun mobil confirm-calories oqimini o'zgarishsiz ishlatadi.
    """

    permission_classes = [IsPatient]

    @extend_schema(
        request=AnalyzeTextSerializer,
        responses=DietMessageSerializer,
        summary="Ovqatni matn orqali tahlil qilish (kaloriyani AI hisoblaydi)",
    )
    def post(self, request):
        # 1. Limit (photo/chat bilan UMUMIY hisoblanadi)
        limit_info = services.check_daily_limit(request.user)
        if not limit_info["allowed"]:
            return _limit_exceeded_response(limit_info)

        serializer = AnalyzeTextSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 1.1 Guardrail: food_name/note matnida xatarli mavzu bo'lsa bloklash
        user_text = " ".join(
            str(data.get(field) or "") for field in ("food_name", "note")
        ).strip()
        if user_text:
            dangerous, _reason = is_dangerous(user_text)
            if dangerous:
                user_lang = (
                    getattr(getattr(request.user, "settings", None), "language", None)
                    or "uz"
                )
                return Response(
                    {"detail": get_safety_response(user_lang)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 2. Conversation topish yoki yaratish (photo bilan bir xil semantika)
        conv_id = data.get("conversation_id")
        if conv_id:
            try:
                conversation = DietConversation.objects.get(
                    id=conv_id, user=request.user
                )
            except DietConversation.DoesNotExist:
                return Response(
                    {"detail": "Suhbat topilmadi."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            user_lang = (
                getattr(getattr(request.user, "settings", None), "language", None)
                or "uz"
            )
            conversation = DietConversation.objects.create(
                user=request.user,
                title="Ovqat matn tahlili",
                language=user_lang,
            )

        # 3. Prompt — APP tilida (rasm yo'q, mirror emas). Foydalanuvchi bergan
        # miqdor promptga qo'shiladi — text prompt uni ANIQ deb oladi.
        app_lang = get_request_lang(request)
        text_prompt = get_text_analysis_prompt(app_lang)
        extra_parts = [f"Ovqat nomi: {data['food_name']}"]
        if data.get("grams"):
            extra_parts.append(f"Vazn: {data['grams']} gramm")
        if data.get("portion"):
            extra_parts.append(f"Porsiya: {data['portion']}")
        if data.get("pieces"):
            extra_parts.append(f"Soni: {data['pieces']} dona")
        if data.get("note"):
            extra_parts.append(f"Eslatma: {data['note']}")
        text_prompt += "\n\nFoydalanuvchi qo'shimcha:\n" + "\n".join(extra_parts)

        user_context = services.build_user_context(request.user)
        system_prompt = build_system_prompt(app_lang, user_context, mirror=False)

        result = generate_text(
            prompt=text_prompt,
            system_instruction=system_prompt,
            response_schema=FOOD_ANALYSIS_SCHEMA,
            max_tokens=8192,
            # Photo bilan bir xil past temperature — determinizm.
            temperature=0.15,
        )
        if "error" in result:
            return Response(
                {"detail": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 4. Structured JSON parse (photo bilan bir xil helper)
        ai_clean_text, food_data, food_detected = (
            services.parse_food_analysis_response(result["text"] or "")
        )
        if food_detected and not food_data:
            logger.warning(
                "Diet analyze-text: food_detected=true lekin food_data BO'SH — text_len=%s",
                len(result["text"] or ""),
            )
        if not food_detected and not ai_clean_text:
            ai_clean_text = (
                "Bu taomni aniqlay olmadim. Iltimos, ovqat nomini aniqroq yozing."
            )

        # 5. user + assistant xabarlarini birga saqlash (atomic)
        meal_type = data.get("meal_type")
        assistant_metadata: dict = {"food_detected": food_detected}
        if food_detected and food_data:
            assistant_metadata["ai_food_data"] = food_data
            assistant_metadata["confirmed"] = False
            # Analyze-vaqtidagi meal_type — confirm-calories entry yaratganda o'qiydi.
            if meal_type:
                assistant_metadata["meal_type"] = meal_type
            if services.has_diet_pro_feature(request.user, "diet_meal_advice"):
                assistant_metadata["meal_advice"] = services.build_meal_advice(
                    request.user,
                    food_data.get("estimated_calories"),
                    food_data.get("glycemic_load"),
                    meal_type or _meal_type_from_now(),
                )
            else:
                assistant_metadata["meal_advice"] = None

        with transaction.atomic():
            user_msg = DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.USER,
                content=data.get("note") or data["food_name"],
                metadata={
                    "food_name": data["food_name"],
                    "portion": data.get("portion") or None,
                    "grams": data.get("grams"),
                    "pieces": data.get("pieces"),
                    "meal_type": meal_type,
                },
            )
            assistant_msg = DietMessage.objects.create(
                conversation=conversation,
                role=DietMessage.Role.ASSISTANT,
                content=ai_clean_text,
                metadata=assistant_metadata or None,
                tokens_input=result["tokens_input"],
                tokens_output=result["tokens_output"],
            )
            conversation.save(update_fields=["updated_at"])

        services.increment_usage(
            request.user,
            tokens_input=result["tokens_input"],
            tokens_output=result["tokens_output"],
        )

        return Response(
            {
                "conversation_id": conversation.id,
                "food_detected": food_detected,
                "user_message": DietMessageSerializer(user_msg).data,
                "assistant_message": DietMessageSerializer(assistant_msg).data,
            }
        )


