from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar
from .common import _assert_patient_connected,_filter_diet_history_qs,_parse_query_date


@extend_schema(tags=["Diet AI - Doctor"])
class DoctorDietRestrictionViewSet(viewsets.ModelViewSet):
    """Doctor — bemor uchun parhez cheklovlarini boshqarish."""

    permission_classes = [IsVerifiedDoctor]
    serializer_class = DietRestrictionSerializer
    queryset = DietRestriction.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DietRestriction.objects.none()
        # Doctor faqat o'zi yaratganlarini ko'radi
        return DietRestriction.objects.filter(doctor=self.request.user).select_related(
            "patient"
        )

    @extend_schema(summary="Mening qo'ygan cheklovlarim")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Cheklov qo'shish (patient ID majburiy)")
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        patient = serializer.validated_data["patient"]
        ok, err = _assert_patient_connected(request.user, patient.id)
        if not ok:
            return Response(
                {"patient": "Bu bemor sizning ro'yxatingizda yo'q."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        restriction = serializer.save(doctor=request.user)
        return Response(
            DietRestrictionSerializer(restriction).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Cheklov yangilash")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(summary="Cheklov yangilash (qisman)")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Cheklovni o'chirish")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=["Diet AI - Doctor"])
class DoctorPatientRestrictionsView(APIView):
    """Doctor — bemor cheklovlarini ko'rish (patient_id bo'yicha)."""

    permission_classes = [IsVerifiedDoctor]

    @extend_schema(
        responses=DietRestrictionSerializer(many=True),
        summary="Bemorning barcha cheklovlari",
    )
    def get(self, request, patient_id=None):
        ok, err = _assert_patient_connected(request.user, patient_id)
        if not ok:
            return err

        qs = DietRestriction.objects.filter(patient_id=patient_id).select_related(
            "doctor"
        )
        return Response(DietRestrictionSerializer(qs, many=True).data)


@extend_schema(tags=["Diet AI - Doctor"])
class DoctorPatientDietHistoryView(APIView):
    """Doctor — bemorning parhez tarixini ko'rish (DietEntry ro'yxati).

    Faqat accepted status'dagi DoctorPatient bog'lanishlari uchun.
    Query params patient endpointi kabi: ?date=2026-04-20 yoki ?from=...&to=...
    """

    permission_classes = [IsVerifiedDoctor]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        summary="Bemor parhez tarixi (doctor uchun)",
        description=(
            "Query: ?date=YYYY-MM-DD (bitta kun), yoki ?from=...&to=... (oraliq). "
            "Parametr berilmasa: oxirgi 30 kun. "
            "?date= berilganda — target_calories (doctor belgilagan, yo'q bo'lsa null) "
            "va consumed_calories (shu kun yig'indisi) qaytariladi; aks holda ikkalasi null."
        ),
    )
    def get(self, request, patient_id=None):
        ok, err = _assert_patient_connected(request.user, patient_id)
        if not ok:
            return err

        target_calories: int | None = None
        consumed_calories: int | None = None
        target_date, date_err = _parse_query_date(request)
        if date_err:
            return date_err
        if target_date is not None:
            limit_obj = DailyCalorieLimit.objects.filter(patient_id=patient_id).first()
            target_calories = limit_obj.calories if limit_obj else None
            # READ oqimi — yo'q indicator type'ni yaratmaymiz (side-effect'siz)
            cal_type = services.get_macros_types(create_missing=False).get("calories")
            if cal_type is not None:
                total = HealthIndicator.objects.filter(
                    user_id=patient_id, indicator_type=cal_type, date=target_date
                ).aggregate(total=Sum("value"))["total"] or Decimal(0)
                consumed_calories = int(total)
            else:
                consumed_calories = 0

        qs = _filter_diet_history_qs(
            DietEntry.objects.filter(user_id=patient_id).select_related("ai_message"),
            request,
        )
        return Response(
            {
                "target_calories": target_calories,
                "consumed_calories": consumed_calories,
                "entries": DietEntrySerializer(qs, many=True).data,
            }
        )


@extend_schema(tags=["Diet AI - Doctor"])
class DoctorDietConversationViewSet(viewsets.ReadOnlyModelViewSet):
    """Doctor — o'z bemorining Diet AI suhbatlarini ko'rish (read-only).

    Faqat accepted status'dagi DoctorPatient bog'lanishlari uchun.
    URL: /diet/doctor/patients/{patient_id}/conversations/
    """

    permission_classes = [IsVerifiedDoctor]
    queryset = DietConversation.objects.none()

    def _is_connected(self):
        """`patient_id` URL kwarg'i bo'yicha ACCEPTED bog'lanishni tekshiradi."""
        ok, _ = _assert_patient_connected(
            self.request.user, self.kwargs.get("patient_id")
        )
        return ok

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DietConversation.objects.none()
        if not self._is_connected():
            return DietConversation.objects.none()
        return (
            DietConversation.objects.filter(user_id=self.kwargs.get("patient_id"))
            .select_related("user")
            .prefetch_related("messages")
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return DietConversationDetailSerializer
        return DietConversationListSerializer

    @extend_schema(summary="Bemorning Diet AI suhbatlari (list)")
    def list(self, request, *args, **kwargs):
        # Bog'lanmagan vs suhbat yo'q — farqlash uchun alohida tekshiruv
        if not self._is_connected():
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Bemor Diet AI suhbati (detail — to'liq xabarlar + stats)")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# --- ADMIN ---


