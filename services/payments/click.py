"""Click provider — paytechuz ClickGateway o'ralmasi."""

from typing import TYPE_CHECKING

from django.conf import settings
from paytechuz.gateways.click import ClickGateway

from .base import BasePaymentProvider, build_return_url

if TYPE_CHECKING:
    from app.payments.models import Payment


class ClickProvider(BasePaymentProvider):
    name = "click"

    def __init__(self):
        cfg = settings.PAYTECHUZ["CLICK"]
        self.gateway = ClickGateway(
            service_id=cfg["SERVICE_ID"],
            merchant_id=cfg["MERCHANT_ID"],
            merchant_user_id=cfg["MERCHANT_USER_ID"],
            secret_key=cfg["SECRET_KEY"],
            is_test_mode=cfg["IS_TEST_MODE"],
        )

    def create_payment(
        self, payment: "Payment", return_url: str | None = None
    ) -> str:
        return self.gateway.create_payment(
            id=payment.id,
            amount=payment.amount,
            return_url=return_url or build_return_url(payment),
        )
