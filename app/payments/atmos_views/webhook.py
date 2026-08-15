from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _decimal_to_tiyin  # underscore helper (star bermaydi)

@extend_schema(tags=["Payments - Webhook"])
class AtmosWebhookView(APIView):
    """Atmos callback — to'lov muvaffaqiyatli tasdiqlangach Atmos yuboradi.

    Atmos faqat success holatda webhook yuboradi (docs: Callback API).
    Yuboriladigan field'lar: store_id, transaction_id, transaction_time,
    amount, invoice, sign (MD5 hash).

    Idempotent: _complete_payment ikki marta chaqirilsa ham bir marta ishlaydi.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        from ..views import _complete_payment

        body = request.data if isinstance(request.data, dict) else {}
        logger.info(
            "Atmos webhook keldi: ip=%s body=%s",
            request.META.get("REMOTE_ADDR"), str(body)[:500],
        )

        # Auth — MD5 sign tekshiruvi (services/payments/atmos.py:verify_webhook)
        if not atmos_client.verify_webhook(body):
            logger.warning("Atmos webhook: sign noto'g'ri yoki yo'q")
            return Response(
                {"status": 0, "message": "Invalid sign"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Payment ni topish — `account` (bizning Payment.id) orqali
        account = body.get("account")
        payment = None
        if account is not None:
            try:
                payment = Payment.objects.filter(
                    id=int(account),
                    provider=Payment.Provider.ATMOS,
                ).first()
            except (TypeError, ValueError):
                pass

        if not payment:
            logger.warning(
                "Atmos webhook: Payment topilmadi account=%s", account,
            )
            return Response(
                {"status": 0, "message": f"{account} raqamli invoys tizimda mavjud emas"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Amount tekshiruvi — fraud signal
        received_amount = body.get("amount")
        try:
            received_tiyin = int(received_amount)
            expected_tiyin = _decimal_to_tiyin(payment.amount)
        except (TypeError, ValueError):
            received_tiyin = expected_tiyin = None
        if received_tiyin != expected_tiyin:
            logger.critical(
                "Atmos webhook AMOUNT MISMATCH: payment=%s expected=%s received=%s",
                payment.id, expected_tiyin, received_amount,
            )
            return Response(
                {"status": 0, "message": "Amount mismatch"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Atmos webhook yuborganida tranzaksiya muvaffaqiyatli bo'lgan
        _complete_payment(payment.id)

        return Response({"status": 1, "message": "muvaffaqiyatli"})
