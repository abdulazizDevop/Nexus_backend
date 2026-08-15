from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _atmos_error_response, _decimal_to_tiyin  # underscore helper (star bermaydi)

@extend_schema(tags=["Payments - Atmos (Patient)"])
class AtmosPayView(APIView):
    """Saqlangan karta orqali to'lov — 1-bosqich (SMS yuboriladi)."""

    permission_classes = [IsPatient]
    serializer_class = AtmosPaySerializer

    @extend_schema(
        request=AtmosPaySerializer,
        responses={
            200: AtmosPayResponseSerializer,
            400: OpenApiResponse(description="Validatsiya yoki Atmos xatosi"),
            404: OpenApiResponse(description="Plan/Tariff/Karta topilmadi"),
            409: OpenApiResponse(description="Aktiv Pro obuna mavjud"),
        },
        summary="Atmos to'lov boshlash (saqlangan karta orqali)",
    )
    def post(self, request):
        serializer = AtmosPaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        card = AtmosSavedCard.objects.filter(
            id=data["saved_card_id"], user=request.user
        ).first()
        if not card:
            return Response(
                {"detail": "Saqlangan karta topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not card.card_number:
            return Response(
                {"detail": "Karta eski formatda saqlangan. Iltimos, kartani qaytadan ulang."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if data["purpose"] == "pro_subscription":
            payment, err = self._create_pro_payment(request.user, data["plan_id"])
        else:
            payment, err = self._create_tariff_payment(
                request.user, data["tariff_id"], data["doctor_id"]
            )
        if err:
            return err

        try:
            create_resp = atmos_client.pay_create(
                amount=_decimal_to_tiyin(payment.amount),
                account=str(payment.id),
            )
            atmos_tx_id = create_resp.get("transaction_id")
            if not atmos_tx_id:
                raise AtmosError("invalid_response", "transaction_id javobda yo'q")

            payment.provider_transaction_id = str(atmos_tx_id)
            payment.save(update_fields=["provider_transaction_id"])

            atmos_client.pay_pre_apply(
                transaction_id=atmos_tx_id,
                card_number=card.card_number,
                expiry=card.expiry,
            )
        except AtmosError as exc:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status"])
            logger.warning(
                "Atmos pay create/pre-apply xatosi: user=%s payment=%s err=%s",
                request.user.id, payment.id, exc,
            )
            return _atmos_error_response(exc)

        logger.info(
            "Atmos to'lov boshlandi: user=%s payment=%s atmos_tx=%s amount=%s purpose=%s",
            request.user.id, payment.id, atmos_tx_id, payment.amount, payment.purpose,
        )
        return Response({"payment_id": payment.id, "otp_required": True})

    def _create_pro_payment(self, user, plan_id):

        if get_active_pro_subscription(user):
            return None, Response(
                {"detail": "Sizda allaqachon aktiv Pro obuna mavjud."},
                status=status.HTTP_409_CONFLICT,
            )

        plan = ProPlan.objects.filter(id=plan_id, is_active=True).first()
        if not plan:
            return None, Response(
                {"detail": "Plan topilmadi."}, status=status.HTTP_404_NOT_FOUND
            )

        # Snapshot shaklini markazlashgan factory quradi (REST oqimi bilan birxil).
        payment = build_pro_payment(user, plan, Payment.Provider.ATMOS)
        return payment, None

    def _create_tariff_payment(self, user, tariff_id, doctor_id):
        tariff = DoctorTariff.objects.filter(
            id=tariff_id,
            doctor_id=doctor_id,
            status=DoctorTariff.Status.APPROVED,
            is_active=True,
        ).first()
        if not tariff:
            return None, Response(
                {"detail": "Tarif topilmadi."}, status=status.HTTP_404_NOT_FOUND
            )

        payment = build_tariff_payment(user, tariff, Payment.Provider.ATMOS)
        return payment, None

@extend_schema(tags=["Payments - Atmos (Patient)"])
class AtmosConfirmView(APIView):
    """To'lov tasdiqlash — 2-bosqich (OTP)."""

    permission_classes = [IsPatient]
    throttle_classes = [OtpConfirmThrottle]
    serializer_class = AtmosConfirmSerializer

    @extend_schema(
        request=AtmosConfirmSerializer,
        responses={
            200: AtmosConfirmResponseSerializer,
            400: OpenApiResponse(description="OTP noto'g'ri yoki Atmos xatosi"),
            404: OpenApiResponse(description="Payment topilmadi"),
        },
        summary="Atmos to'lovni tasdiqlash (OTP)",
    )
    def post(self, request):
        # _complete_payment'ni import qilish bo'shliq ichida — views.py
        # juda katta, top-level import circular bo'lishi mumkin
        from ..views import _complete_payment

        serializer = AtmosConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = Payment.objects.filter(
            id=serializer.validated_data["payment_id"],
            user=request.user,
            provider=Payment.Provider.ATMOS,
        ).first()
        if not payment:
            return Response(
                {"detail": "To'lov topilmadi."}, status=status.HTTP_404_NOT_FOUND
            )

        if payment.status == Payment.Status.COMPLETED:
            return Response(
                {"status": "completed", "ofd_url": payment.metadata.get("ofd_url", "")}
            )

        if not payment.provider_transaction_id:
            return Response(
                {"detail": "Atmos tranzaksiya ID topilmadi — qaytadan urinib ko'ring."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            data = atmos_client.pay_apply(
                transaction_id=int(payment.provider_transaction_id),
                otp=serializer.validated_data["otp"],
            )
        except AtmosError as exc:
            logger.warning(
                "Atmos pay_apply xatosi: user=%s payment=%s err=%s",
                request.user.id, payment.id, exc,
            )
            return _atmos_error_response(exc)

        ofd_url = data.get("ofd_url", "")
        if ofd_url:
            payment.metadata = {**(payment.metadata or {}), "ofd_url": ofd_url}
            payment.save(update_fields=["metadata"])

        _complete_payment(payment.id)

        logger.info(
            "Atmos to'lov tasdiqlandi: user=%s payment=%s ofd=%s",
            request.user.id, payment.id, ofd_url,
        )
        return Response({"status": "success", "ofd_url": ofd_url})


# ---------- Webhook ----------
