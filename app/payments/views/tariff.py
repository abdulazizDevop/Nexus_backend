from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


@extend_schema(tags=["Payments - Doctor tariflari (Patient)"])
class DoctorTariffPublicViewSet(viewsets.ReadOnlyModelViewSet):
    """Patient uchun — doctor approved tariflari"""

    serializer_class = DoctorTariffPublicSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DoctorTariff.objects.none()
        qs = DoctorTariff.objects.filter(
            status=DoctorTariff.Status.APPROVED,
            is_active=True,
            doctor__user__is_active=True,
        ).select_related("doctor__user")
        doctor_id = self.request.query_params.get("doctor_id")
        if doctor_id:
            qs = qs.filter(doctor_id=doctor_id)
        return qs

    @extend_schema(
        operation_id="payments_public_doctor_tariffs_list",
        summary="Doctor tariflari ro'yxati",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="payments_public_doctor_tariff_retrieve",
        summary="Tarif batafsil",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=PurchaseRequestSerializer,
        responses={
            200: InvoiceResponseSerializer,
            409: OpenApiResponse(
                description="Shu doktorning faol tarifi mavjud"
            ),
        },
        summary="Tarifni sotib olish",
    )
    @action(detail=True, methods=["post"], url_path="purchase")
    def purchase(self, request, pk=None):
        tariff = self.get_object()
        serializer = PurchaseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider_name = serializer.validated_data["provider"]
        try:
            provider = get_provider(provider_name)
        except ValueError as e:
            # Exception matnini klientga qaytarmaymiz (info leak) — server'da log.
            logger.warning("Noto'g'ri to'lov provayderi: %s (%s)", provider_name, e)
            return Response({"detail": "Noma'lum to'lov provayderi."}, status=400)

        active_purchase = (
            DoctorTariffPurchase.objects.filter(
                patient=request.user,
                doctor_id=tariff.doctor_id,
                expires_at__gt=timezone.now(),
            )
            .order_by("-expires_at")
            .first()
        )
        if active_purchase:
            return Response(
                {
                    "detail": "Sizda ushbu doktorning faol tarifi mavjud. "
                    "Yangi tarif sotib olish uchun joriy tarif tugashini kuting.",
                    "expires_at": active_purchase.expires_at,
                },
                status=409,
            )

        payment = build_tariff_payment(request.user, tariff, provider_name)
        amount = payment.amount

        try:
            payment_url = provider.create_payment(payment)
        except Exception as exc:
            logger.exception(
                "Tariff purchase: payment_url yaratishda xato user=%s tariff=%s doctor=%s provider=%s payment=%s err=%s",
                request.user.id, tariff.id, tariff.doctor_id, provider_name, payment.id, exc,
            )
            raise

        logger.info(
            "Tariff purchase invoice yaratildi: user=%s tariff=%s(%s) doctor=%s amount=%s provider=%s payment=%s url=%s",
            request.user.id,
            tariff.id,
            tariff.name,
            tariff.doctor_id,
            amount,
            provider_name,
            payment.id,
            payment_url,
        )

        return Response(
            {
                "payment_id": payment.id,
                "payment_url": payment_url,
                "amount": amount,
                "provider": provider_name,
            }
        )


@extend_schema(tags=["Payments - Doctor tariflari (Patient)"])
class MyPurchasesView(APIView):
    """Patient sotib olgan doctor tariflari"""

    permission_classes = [IsPatient]
    serializer_class = DoctorTariffPurchaseSerializer

    @extend_schema(
        summary="Mening sotib olganlarim",
        responses=DoctorTariffPurchaseSerializer(many=True),
    )
    def get(self, request):
        purchases = DoctorTariffPurchase.objects.filter(
            patient=request.user
        ).select_related("doctor__user", "tariff")
        return Response(DoctorTariffPurchaseSerializer(purchases, many=True).data)


# ============ Doctor (o'z tariflari) ============


@extend_schema(tags=["Payments - Doctor"])
class DoctorTariffViewSet(viewsets.ModelViewSet):
    """Doctor o'z tariflarini yaratadi va boshqaradi"""

    serializer_class = DoctorTariffSerializer
    permission_classes = [IsVerifiedDoctor]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DoctorTariff.objects.none()
        profile = getattr(self.request.user, "doctor_profile", None)
        if not profile:
            return DoctorTariff.objects.none()
        return DoctorTariff.objects.filter(doctor=profile)

    def perform_create(self, serializer):

        profile, _ = DoctorProfile.objects.get_or_create(user=self.request.user)
        serializer.save(doctor=profile, status=DoctorTariff.Status.PENDING)

    @extend_schema(
        operation_id="payments_doctor_my_tariffs_list",
        summary="Mening tariflarim",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        operation_id="payments_doctor_my_tariff_retrieve",
        summary="Tarif batafsil",
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Yangi tarif qo'shish")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(summary="Tarifni tahrirlash")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(summary="Tarifni qisman tahrirlash")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Tarifni o'chirish")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=["Payments - Doctor"])
class DoctorBalanceView(APIView):
    """Doctor balans ko'rish"""

    permission_classes = [IsVerifiedDoctor]
    serializer_class = DoctorBalanceSerializer

    @extend_schema(
        summary="Mening balansim",
        responses=DoctorBalanceSerializer,
    )
    def get(self, request):

        profile, _ = DoctorProfile.objects.get_or_create(user=request.user)
        balance, _ = DoctorBalance.objects.get_or_create(doctor=profile)
        return Response(DoctorBalanceSerializer(balance).data)


# ============ Offline to'lov (naqd) + Balans to'ldirish ============


