"""Payme provider — paytechuz PaymeGateway o'ralmasi."""

from typing import TYPE_CHECKING

from django.conf import settings
from paytechuz.gateways.payme import PaymeGateway

from .base import BasePaymentProvider, build_return_url

if TYPE_CHECKING:
    from app.payments.models import Payment


class PaymeProvider(BasePaymentProvider):
    name = "payme"

    def __init__(self):
        cfg = settings.PAYTECHUZ["PAYME"]
        self.gateway = PaymeGateway(
            payme_id=cfg["PAYME_ID"],
            payme_key=cfg["PAYME_KEY"],
            is_test_mode=cfg["IS_TEST_MODE"],
        )
        self._account_field = cfg.get("ACCOUNT_FIELD", "id")

    def create_payment(
        self, payment: "Payment", return_url: str | None = None
    ) -> str:
        # `account_field_name` Payme deeplink URL'idagi parametr nomini belgilaydi
        # (`?ac.{field}={value}`). PAYTECHUZ['PAYME']['ACCOUNT_FIELD']'ni o'zgartirsak,
        # bu yerda ham avtomatik moslashadi — webhook va deeplink mos bo'lib qoladi.
        return self.gateway.create_payment(
            id=payment.id,
            amount=payment.amount,
            return_url=return_url or build_return_url(payment),
            account_field_name=self._account_field,
        )
