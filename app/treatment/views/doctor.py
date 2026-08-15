from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _destroy_with_archived_logs, _today_logs_prefetch  # underscore helper (star bermaydi)

@extend_schema(tags=["Doctor - Muolaja"])
class DoctorTreatmentViewSet(viewsets.ModelViewSet):
    """Doctor — bemorga muolaja yozish va boshqarish"""

    permission_classes = [IsVerifiedDoctor]
    http_method_names = ["get", "post", "put", "delete", "head"]

    def _connected_patient_ids(self):
        """Doctor ACCEPTED bog'langan bemorlarning user_id'lari."""
        profile = getattr(self.request.user, "doctor_profile", None)
        if not profile:
            return []
        return list(
            DoctorPatient.objects.filter(
                doctor=profile, status=DoctorPatient.Status.ACCEPTED
            ).values_list("patient_id", flat=True)
        )

    def _resolve_patient(self, request):
        """`?user=<id>` bemorini qaytaradi + kirish huquqini tekshiradi.

        Ruxsat: doctor bemorga ACCEPTED bog'langan YOKI unga muolaja yozgan
        (created_by) bo'lsa. Aks holda (None, error_response).
        """
        patient_id = request.query_params.get("user")
        if not patient_id:
            return None, Response(
                {"user": "?user=<bemor user id> majburiy."}, status=400
            )
        connected = set(self._connected_patient_ids())
        authored = Treatment.objects.filter(
            created_by=request.user, user_id=patient_id
        ).exists()
        try:
            allowed = int(patient_id) in connected or authored
        except (TypeError, ValueError):
            return None, Response({"user": "Noto'g'ri id."}, status=400)
        if not allowed:
            return None, Response(
                {"detail": "Bu bemorga kirish huquqi yo'q yoki bemor topilmadi."},
                status=404,
            )
        return patient_id, None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Treatment.objects.none()
        user = self.request.user
        base = Treatment.objects.select_related(
            "user", "created_by"
        ).prefetch_related(_today_logs_prefetch())

        # TAHRIR/O'CHIRISH — AYNAN doctor o'zi yozgan (created_by) muolajaga cheklanadi.
        # Bemor bilan bog'lanish keyin uzilsa ham, doctor o'z yozganini tuzatadi (ataylab).
        if self.action in ("update", "partial_update", "destroy"):
            return base.filter(created_by=user)

        # O'QISH (list/retrieve) — doctor ACCEPTED bog'langan bemorlarning BARCHA
        # muolajalarini ko'radi (bemor O'ZI qo'shgani ham — statuslari bilan), va
        # o'zi yozganlarini. Statuslar TreatmentSerializer.today_status orqali keladi.
        qs = base.filter(
            models.Q(created_by=user)
            | models.Q(user_id__in=self._connected_patient_ids())
        )

        # ?user=<patient_user_id> — AYNAN shu bemorning hammasini olish (bog'lanmagan
        # bemor uchun faqat doctor o'zi yozganlari ko'rinadi — leak yo'q).
        patient = self.request.query_params.get("user")
        if patient:
            qs = qs.filter(user_id=patient)
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return DoctorTreatmentCreateSerializer
        return TreatmentSerializer

    @extend_schema(summary="Doctor yozgan muolajalar ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=DoctorTreatmentCreateSerializer,
        responses=TreatmentSerializer,
        summary="Bemorga muolaja yozish",
        description="Doctor bemorga dori, mashq yoki boshqa muolaja yozadi.",
    )
    def create(self, request, *args, **kwargs):
        serializer = DoctorTreatmentCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        patient = get_object_or_404(User, id=serializer.validated_data["patient_id"])
        data = serializer.validated_data.copy()
        data.pop("patient_id")
        treatment = Treatment.objects.create(
            user=patient,
            created_by=request.user,
            **data,
        )

        return Response(TreatmentSerializer(treatment).data, status=201)

    @extend_schema(summary="Muolajani yangilash")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Muolajani o'chirish",
        description=(
            "Doctor yozgan muolajani o'chiradi. COMPLETED loglar tarix uchun saqlanadi."
        ),
    )
    def destroy(self, request, *args, **kwargs):
        _destroy_with_archived_logs(self.get_object())
        return Response(status=204)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Bemorning muolaja loglari (tarix)",
        description=(
            "Doctor bog'langan bemorning muolaja bajarilish tarixini oladi. "
            "?user=<bemor user id> majburiy, ?date=YYYY-MM-DD ixtiyoriy. "
            "O'CHIRILGAN muolajalarning saqlangan loglari (treatment=null, "
            "treatment_title/treatment_type snapshot bilan) ham qaytadi."
        ),
        parameters=[
            OpenApiParameter("user", int, description="Bemor user id (majburiy)"),
            OpenApiParameter("date", str, description="YYYY-MM-DD (ixtiyoriy)"),
        ],
        responses=TreatmentLogSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="logs")
    def patient_logs(self, request):
        patient_id, err = self._resolve_patient(request)
        if err:
            return err
        qs = TreatmentLog.objects.filter(user_id=patient_id).select_related("treatment")
        date = request.query_params.get("date")
        if date:
            qs = qs.filter(date=date)
        return Response(TreatmentLogSerializer(qs, many=True).data)

    @extend_schema(
        summary="Bemorning oylik statistikasi",
        description=(
            "Bemorning completion/streak statistikasi (o'chirilgan muolajalar "
            "tarixi ham hisobga olinadi). ?user=<bemor user id> majburiy."
        ),
        parameters=[OpenApiParameter("user", int, description="Bemor user id (majburiy)")],
    )
    @action(detail=False, methods=["get"], url_path="stats")
    def patient_stats(self, request):
        patient_id, err = self._resolve_patient(request)
        if err:
            return err
        patient = User.objects.filter(id=patient_id).first()
        if not patient:
            return Response({"detail": "Bemor topilmadi."}, status=404)
        return Response(compute_treatment_stats(patient))
