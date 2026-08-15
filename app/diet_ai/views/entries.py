from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar
from .common import _meal_type_from_now


@extend_schema(tags=["Diet AI - Patient"])
class DietConfirmCaloriesView(APIView):
    """AI tahlilini tasdiqlab, kaloriyalarni kunlik hisobga qo'shish.

    Flow:
        1. User rasm yuboradi → AI tahlil qiladi → assistant message metadata'sida
           ai_food_data = {food_name, estimated_calories, portion_grams} saqlanadi.
        2. User "To'g'ri, qo'shish" tugmasini bosadi → shu endpoint chaqiriladi.
        3. HealthIndicator yoziladi (Kaloriya indicator_type, bugungi sana).
        4. Kunlik kaloriya chegarasi bilan solishtiriladi — over_limit warning.
    """

    permission_classes = [IsPatient]

    @extend_schema(
        request=ConfirmCaloriesSerializer,
        responses=ConfirmCaloriesResponseSerializer,
        summary="AI tahlilini tasdiqlab, kunlik kaloriya + macros'ga qo'shish",
        description=(
            "message_id URL'da. Request body'da calories (ixtiyoriy) — agar user "
            "AI estimated_calories dan farqli raqam kiritsa. Aks holda metadata'dagi "
            "ai_food_data ishlatiladi. Kaloriya + uglevod + oqsil + yog' bir vaqtda "
            "HealthIndicator'ga yoziladi va DietEntry yaratiladi (keyin o'chirish uchun)."
        ),
    )
    def post(self, request, message_id=None):
        # 1. Body validatsiya (lock olishdan oldin — tez rad etish)
        serializer = ConfirmCaloriesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_calories = serializer.validated_data.get("calories")

        today = timezone.localdate()

        # 2. Atomic + select_for_update — idempotensiyani lock ichida tekshiramiz.
        # Bir vaqtli (double-tap / retry) so'rovlar birin-ketin bajariladi,
        # ikkinchisi confirmed=True'ni ko'rib double-count'siz qaytadi.
        # Eslatma: early-return'lar (404/400) hech narsa yozilmasdan oldin
        # bo'lgani uchun bo'sh tranzaksiyani commit qiladi — zararsiz.
        with transaction.atomic():
            try:
                msg = (
                    DietMessage.objects.select_for_update()
                    .select_related("conversation")
                    .get(
                        id=message_id,
                        conversation__user=request.user,
                        role=DietMessage.Role.ASSISTANT,
                    )
                )
            except DietMessage.DoesNotExist:
                return Response(
                    {"detail": "Xabar topilmadi yoki sizga tegishli emas."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            metadata = msg.metadata or {}
            food_data = metadata.get("ai_food_data") or {}
            if not food_data.get("estimated_calories"):
                return Response(
                    {"detail": "Bu xabarda AI kaloriya tahlili yo'q."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Idempotency tekshiruvi — lock ichida (race'siz)
            if metadata.get("confirmed"):
                return Response(
                    {"detail": "Bu xabar allaqachon tasdiqlangan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Qiymatlar (user override > AI)
            calories = int(user_calories or food_data["estimated_calories"])
            carbs = int(food_data.get("carbs_grams") or 0)
            protein = int(food_data.get("protein_grams") or 0)
            fat = int(food_data.get("fat_grams") or 0)
            food_name = food_data.get("food_name") or "Ovqat"
            glycemic_load = food_data.get("glycemic_load") or None
            portion_grams = food_data.get("portion_grams") or None
            ingredients = food_data.get("ingredients") or []
            # meal_type ustunligi: confirm request > analyze-vaqtidagi metadata > soatdan
            meal_type = (
                serializer.validated_data.get("meal_type")
                or metadata.get("meal_type")
                or _meal_type_from_now()
            )

            # Rasm assistant'da emas, user message'da. Shu suhbatdagi
            # assistant'dan oldingi rasmli user message'ni topamiz.
            user_msg_with_image = (
                DietMessage.objects.filter(
                    HAS_IMAGE,
                    conversation=msg.conversation,
                    role=DietMessage.Role.USER,
                    created_at__lt=msg.created_at,
                )
                .order_by("-created_at")
                .first()
            )
            entry_image_key = (
                user_msg_with_image.image_key if user_msg_with_image else None
            )
            source = (
                DietEntry.Source.AI_PHOTO
                if entry_image_key
                else DietEntry.Source.AI_TEXT
            )

            entry = DietEntry.objects.create(
                user=request.user,
                date=today,
                food_name=food_name,
                calories=calories,
                carbs_grams=carbs,
                protein_grams=protein,
                fat_grams=fat,
                meal_type=meal_type,
                glycemic_load=glycemic_load,
                portion_grams=portion_grams,
                ingredients=ingredients,
                source=source,
                ai_message=msg,
                image_key=entry_image_key,
            )
            services.add_to_daily_indicators(
                user=request.user,
                date=today,
                calories=calories,
                carbs=carbs,
                protein=protein,
                fat=fat,
                diet_entry_id=entry.id,
            )
            metadata["confirmed"] = True
            metadata["confirmed_calories"] = calories
            metadata["confirmed_entry_id"] = entry.id
            metadata["confirmed_at"] = timezone.now().isoformat()
            msg.metadata = metadata
            msg.save(update_fields=["metadata"])

        # 6. Daily summary + ogohlantirish
        summary = services.get_daily_summary(request.user, today)
        cal_stat = summary["calories"]
        warning = None
        if cal_stat["over_limit"] and cal_stat["limit"]:
            over_by = cal_stat["consumed"] - cal_stat["limit"]
            warning = (
                f"Kunlik chegaradan {over_by} kcal oshib ketdi. "
                f"Kechgacha kam kaloriyali ovqatni tavsiya qilamiz."
            )
        elif (
            cal_stat["remaining"] is not None
            and cal_stat["limit"]
            and (cal_stat["remaining"] < cal_stat["limit"] * 0.1)
        ):
            warning = f"Kunlik chegaraga yaqin: faqat {cal_stat['remaining']} kcal qoldi."

        return Response(
            {
                "confirmed": True,
                "entry_id": entry.id,
                "added": {
                    "calories": calories,
                    "carbs_grams": carbs,
                    "protein_grams": protein,
                    "fat_grams": fat,
                },
                "today": summary,
                "warning": warning,
            }
        )


@extend_schema(tags=["Diet AI - Patient"])
class DietMessageFeedbackView(APIView):
    """Assistant xabariga sifat feedbacki (to'g'ri/noto'g'ri) — AI monitoring.

    Mobil foydalanuvchi AI tahlilini "to'g'ri"/"noto'g'ri" deb belgilaydi.
    Xabar metadata.feedback ga saqlanadi; takroriy yuborilsa oxirgisi yoziladi.
    """

    permission_classes = [IsPatient]

    @extend_schema(
        request=MessageFeedbackSerializer,
        responses={204: None},
        summary="AI xabariga baho berish (correct/incorrect)",
        description=(
            "Body: {\"verdict\": \"correct\" | \"incorrect\", \"comment\"?: \"...\"}. "
            "metadata.feedback ga yoziladi (verdict + at + ixtiyoriy comment). "
            "Takroriy so'rov — oxirgisi yoziladi. Faqat assistant xabari, faqat egasi."
        ),
    )
    def post(self, request, message_id=None):
        ser = MessageFeedbackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        with transaction.atomic():
            try:
                msg = (
                    DietMessage.objects.select_for_update()
                    .get(
                        id=message_id,
                        conversation__user=request.user,
                        role=DietMessage.Role.ASSISTANT,
                    )
                )
            except DietMessage.DoesNotExist:
                return Response(
                    {"detail": "Xabar topilmadi yoki sizga tegishli emas."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            feedback = {
                "verdict": ser.validated_data["verdict"],
                "at": timezone.now().isoformat(),
            }
            comment = ser.validated_data.get("comment")
            if comment:
                feedback["comment"] = comment

            metadata = msg.metadata or {}
            metadata["feedback"] = feedback  # takror → oxirgisi
            msg.metadata = metadata
            msg.save(update_fields=["metadata"])

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Diet AI - Patient"])
class DietManualEntryView(APIView):
    """Patient qo'lda ovqat kiritish — kaloriya + uglevod/oqsil/yog'."""

    permission_classes = [IsPatient]

    @extend_schema(
        request=ManualDietEntrySerializer,
        responses=DietEntrySerializer,
        summary="Qo'lda ovqat kiritish",
        description=(
            "Patient taom nomi va kaloriyani kiritadi (macros ixtiyoriy). "
            "DietEntry yaratiladi + 4 ta HealthIndicator qiymati oshiriladi (atomic). "
            "Keyin history'dan o'chirish imkoniyati bor."
        ),
    )
    def post(self, request):
        serializer = ManualDietEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entry_date = data.get("date") or timezone.localdate()

        with transaction.atomic():
            entry = DietEntry.objects.create(
                user=request.user,
                date=entry_date,
                food_name=data["food_name"],
                calories=data["calories"],
                carbs_grams=data.get("carbs_grams", 0),
                protein_grams=data.get("protein_grams", 0),
                fat_grams=data.get("fat_grams", 0),
                meal_type=data.get("meal_type") or _meal_type_from_now(),
                source=DietEntry.Source.MANUAL,
            )
            services.add_to_daily_indicators(
                user=request.user,
                date=entry_date,
                calories=entry.calories,
                carbs=entry.carbs_grams,
                protein=entry.protein_grams,
                fat=entry.fat_grams,
                diet_entry_id=entry.id,
            )

        return Response(
            DietEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


