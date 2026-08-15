from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar


@extend_schema(tags=["Medical - Tibbiy karta"])
class MedicalCardViewSet(viewsets.GenericViewSet):
    """Tibbiy karta — bemor va doctor uchun.

    Endpointlar:
        GET   /medical/card/me/             — bemor o'zi
        PATCH /medical/card/me/             — bemor o'zi
        GET   /medical/card/{patient_id}/   — doctor (bog'langan bemor uchun)
        PATCH /medical/card/{patient_id}/   — doctor
    """

    serializer_class = MedicalCardSerializer
    permission_classes = [IsAuthenticated]
    queryset = MedicalCard.objects.none()

    def _get_or_create_card(self, user):
        card, _ = MedicalCard.objects.get_or_create(user=user)
        return card

    @extend_schema(summary="O'z tibbiy kartam (bemor)")
    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        # Audit H4 - CLAUDE.md qoidasi: view'da scope JWT'dan o'qilsin.
        # Aks holda admin doctor sifatida switch qilganda /me ishlamaydi
        # yoki aksincha doctor token bilan kim qaerda patient bo'lmagani
        # tekshirilmaydi.
        if get_request_role(request) != "patient":
            return Response(
                {"detail": "Faqat bemor o'z kartasiga kira oladi."}, status=403
            )
        card = self._get_or_create_card(request.user)
        if request.method == "PATCH":
            serializer = self.get_serializer(card, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(self.get_serializer(card).data)

    @extend_schema(
        summary="Bemor tibbiy kartasi",
        description="Doctor o'z bemorlarining tibbiy kartasini ko'radi/tahrirlaydi.",
    )
    @action(
        detail=False,
        methods=["get", "patch"],
        url_path=r"(?P<patient_id>\d+)",
    )
    def patient_card(self, request, patient_id=None):
        target, err = resolve_target_user(request, patient_id)
        if err:
            return err
        card = self._get_or_create_card(target)
        if request.method == "PATCH":
            serializer = self.get_serializer(card, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(self.get_serializer(card).data)


# --- Medical Conditions ---


# --- Tibbiy karta summary (doctor side, aggregated) ---


@extend_schema(tags=["Medical - Tibbiy karta"])
class MedicalCardSummaryView(APIView):
    """Bemor tibbiy karta summary — qon guruhi, asosiy kasallik, holat,
    analizlar (so'nggi + tayinlangan), allergiyalar — bitta so'rovda.

    Faqat doctor bemoriga kira oladi (DoctorPatient.ACCEPTED).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Tibbiy karta umumiy ko'rinishi (doctor)",
        responses=MedicalCardSummarySerializer,
    )
    def get(self, request, patient_id: int):
        target, err = resolve_target_user(request, patient_id)
        if err:
            return err

        card, _ = MedicalCard.objects.get_or_create(user=target)

        analyses_qs = (
            Analysis.objects.filter(patient=target)
            .select_related("type", "doctor")
            .prefetch_related("indicators")
        )
        # So'nggi natija/yakunlangan analizlar (submitted yoki reviewed) — top 5
        recent_qs = analyses_qs.filter(
            status__in=[Analysis.Status.SUBMITTED, Analysis.Status.REVIEWED]
        ).order_by("-submitted_at", "-created_at")[:5]
        # Tayinlangan / kutilayotgan
        pending_qs = analyses_qs.filter(status=Analysis.Status.PRESCRIBED).order_by(
            "deadline_at"
        )[:5]

        allergies_qs = MedicalCondition.objects.filter(
            user=target, type=MedicalCondition.Type.ALLERGY
        )

        # Bemor profil ma'lumotlari.
        # User.avatar CharField (S3 key) — Bunny CDN signed URL ishlatamiz.
        from ..serializers import _signed_download

        avatar_url = _signed_download(target.avatar)

        # Yosh — User.birth_date dan hisoblanadi (Patient'da age maydoni yo'q).
        age = None
        if target.birth_date:
            today = timezone.localdate()
            age = today.year - target.birth_date.year - (
                (today.month, today.day)
                < (target.birth_date.month, target.birth_date.day)
            )
        # Jins — User.sex maydoni ("male"/"female"); Patient'da gender yo'q.
        gender = target.sex or None

        data = {
            "patient": {
                "id": target.id,
                "full_name": target.full_name or "",
                "phone": target.phone,
                "age": age,
                "gender": gender,
                "avatar_url": avatar_url,
            },
            "card": MedicalCardSerializer(card).data,
            "analyses_recent": AnalysisListSerializer(recent_qs, many=True).data,
            "analyses_pending": AnalysisListSerializer(pending_qs, many=True).data,
            "analyses_total": analyses_qs.count(),
            "analyses_pending_count": analyses_qs.filter(
                status=Analysis.Status.PRESCRIBED
            ).count(),
            "allergies": MedicalConditionSerializer(allergies_qs, many=True).data,
            "allergies_count": allergies_qs.count(),
        }
        return Response(data)
