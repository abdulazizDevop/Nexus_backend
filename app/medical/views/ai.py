from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar


@extend_schema(tags=["Medical - AI"])
class MedicalAudioUploadUrlView(APIView):
    """Doctor medical note uchun audio yuklash presigned URL oladi."""

    permission_classes = [IsVerifiedDoctor]

    @extend_schema(
        request=AudioUploadUrlRequestSerializer,
        responses=AudioUploadUrlResponseSerializer,
        summary="Medical note audio yuklash URL",
        description=(
            "Doctor ovoz yozib yuboradi. Mobile flow: "
            "1) Bu endpoint dan upload_url + audio_key olinadi, "
            "2) PUT {upload_url} bilan audio S3 ga yuklanadi (15 daqiqa muddat), "
            "3) POST /medical/notes/ai-draft/ {audio_key, patient_id} bilan tahlil."
        ),
    )
    def post(self, request):
        serializer = AudioUploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_type = serializer.validated_data["file_type"]

        item = build_upload_item(
            f"medical-audio/{request.user.id}/", file_type, fallback_ext="webm"
        )
        # Bu endpoint javobda `file_key` o'rniga `audio_key` qaytaradi.
        return Response(
            {
                "upload_url": item["upload_url"],
                "audio_key": item["file_key"],
                "expires_in": item["expires_in"],
            }
        )


@extend_schema(tags=["Medical - AI"])
class MedicalNoteAIDraftView(APIView):
    """Audio → transcription + professional medical note draft.

    Gemini audio'ni transcribe qiladi va bemor kontekstini hisobga olib
    professional klinik yozuv shakliga solib beradi. Doctor keyin uni
    tahrirlab POST /medical/notes/ ga yuboradi.
    """

    permission_classes = [IsVerifiedDoctor]

    @extend_schema(
        request=MedicalNoteAIDraftRequestSerializer,
        responses=MedicalNoteAIDraftResponseSerializer,
        summary="Audio → AI medical note draft",
    )
    def post(self, request):
        import json as _json



        serializer = MedicalNoteAIDraftRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        patient_id = data["patient_id"]

        # 1. Permission: bemor doctor'ga bog'langanmi (accepted)
        if not doctor_can_access_patient(request.user, patient_id):
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # XAVFSIZLIK: audio_key FAQAT o'z prefiksida bo'lsin — aks holda bucket'dagi
        # istalgan faylni o'qish mumkin (cross-tenant arbitrary read). Upload-url
        # har doim medical-audio/{user.id}/ beradi.
        if not str(data["audio_key"]).startswith(f"medical-audio/{request.user.id}/"):
            return Response(
                {"detail": "Noto'g'ri audio_key."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 2. Audio'ni S3 dan yuklab olish
        try:
            audio_bytes, audio_mime = download_file_bytes(data["audio_key"])
        except Exception:
            return Response(
                {"detail": "Audio topilmadi yoki yuklab bo'lmadi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Hajm cheklovi — 20 MB
        MAX_AUDIO_BYTES = 20 * 1024 * 1024
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            return Response(
                {"detail": "Audio hajmi 20 MB dan oshmasligi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4. Bemor konteksti
        patient = User.objects.filter(id=patient_id).first()
        context_parts = []
        if patient:
            context_parts.append(
                f"Bemor: {patient.full_name or '—'}, telefon: {patient.phone}"
            )
            card = MedicalCard.objects.filter(user=patient).first()
            if card:
                card_info = []
                if card.blood_type:
                    card_info.append(f"qon guruhi: {card.blood_type}")
                if card.primary_disease:
                    card_info.append(f"asosiy kasallik: {card.primary_disease}")
                if card.current_status:
                    card_info.append(
                        f"holat: {card.get_current_status_display()}"
                    )
                if card_info:
                    context_parts.append("Tibbiy karta: " + ", ".join(card_info))
                if card.notes:
                    context_parts.append(f"Karta izohlari: {card.notes}")

            conds = MedicalCondition.objects.filter(user=patient).order_by(
                "-created_at"
            )[:10]
            if conds:
                cond_lines = [
                    f"{c.get_type_display()}: {c.name}"
                    + (f" ({c.get_severity_display()})" if c.severity else "")
                    for c in conds
                ]
                context_parts.append(
                    "Kasalliklar/allergiya: " + "; ".join(cond_lines)
                )

            prev_notes = MedicalNote.objects.filter(user=patient).order_by(
                "-created_at"
            )[:3]
            if prev_notes:
                prev_text = "\n---\n".join(
                    f"[{n.created_at:%Y-%m-%d}] {n.text[:300]}" for n in prev_notes
                )
                context_parts.append("Oxirgi klinik yozuvlar:\n" + prev_text)

        context_block = "\n".join(context_parts) or "(Kontekst yo'q)"

        language = data.get("language") or "uz"
        lang_instruction = {
            "uz": "O'zbek lotin",
            "uz-cyrl": "Ўзбек кирилл",
            "ru": "Русский",
        }.get(language, "O'zbek lotin")

        # 5. Gemini prompt — structured JSON
        prompt = (
            f"Siz tibbiy hujjatlashtirishga yordam beruvchi AI assistent. "
            f"Shifokor {lang_instruction} tilida bemor haqida klinik yozuv "
            f"diktovka qildi. Sizning vazifangiz:\n\n"
            f"1. AUDIO → matn (transcription): shifokor aytganini aynan yozib oling, "
            f"tibbiy terminlarni to'g'ri ajrating.\n"
            f"2. TRANSCRIPTION → DRAFT: uni professional klinik yozuv shakliga keltiring. "
            f"Strukturali markdown, paragraflar/bulletlar bilan, tibbiy bo'lmagan so'zlarni "
            f"tahrirlang, qaytarilishlarni olib tashlang. Bemor kontekstini (quyida) "
            f"hisobga oling — lekin CHEGARANI BUZMANG: yangi diagnoz qo'shmang, shifokor "
            f"aytmagan narsani yozmang. Draft — faqat shifokor aytganini format qiladi.\n\n"
            f"BEMOR KONTEKSTI:\n{context_block}\n\n"
            f"Til: {lang_instruction}"
        )

        schema = {
            "type": "object",
            "properties": {
                "transcription": {
                    "type": "string",
                    "description": "Audio'dagi gaplar aynan (raw transcript)",
                },
                "draft_text": {
                    "type": "string",
                    "description": "Professional klinik yozuv (markdown)",
                },
            },
            "required": ["transcription", "draft_text"],
        }

        result = generate_with_audio(
            prompt=prompt,
            audio_bytes=audio_bytes,
            audio_mime_type=audio_mime or "audio/webm",
            response_schema=schema,
            max_tokens=8192,
        )

        if "error" in result:
            return Response(
                {"detail": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # 6. JSON parse
        raw_text = result["text"] or ""
        try:
            parsed = _json.loads(raw_text)
            transcription = (parsed.get("transcription") or "").strip()
            draft_text = (parsed.get("draft_text") or "").strip()
        except (ValueError, _json.JSONDecodeError):
            transcription = raw_text.strip()
            draft_text = raw_text.strip()

        return Response(
            {
                "transcription": transcription,
                "draft_text": draft_text,
                "tokens_used": result.get("tokens_input", 0)
                + result.get("tokens_output", 0),
            }
        )


# ---------------------------------------------------------------------------
# ANALIZLAR (Analysis prescriptions + patient submissions)
# ---------------------------------------------------------------------------


# --- Katalog (AnalysisType / Indicator / Preparation) ---


