"""To'lov provayderlari uchun abstract base class.

Har provider (Payme, Click, Uzum) shu klassdan meros oladi va
paytechuz gateway'ini o'rab beradi. Webhook'larni paytechuz o'zi handle qiladi
(app/payments/views.py'dagi *WebhookView lar orqali) — bu yerda faqat
checkout URL generatsiyasi mavjud.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from django.conf import settings

if TYPE_CHECKING:
    from app.payments.models import Payment


def build_return_url(payment: "Payment", status: str = "success") -> str:
    """Mobile deep-link uchun return URL yaratadi.

    Format: `https://app.mediik.uz/payment/return?payment_id=N&status=success`

    iOS Universal Links / Android App Links ushbu URL'ni Mediik app'ga
    yo'naltiradi (AASA + assetlinks.json fayllar `app.mediik.uz`'da host
    qilingan bo'lsa). App o'rnatilmagan bo'lsa, brauzer'da fallback sahifa
    ochiladi.
    """
    base = settings.PAYMENT_RETURN_URL  # masalan https://app.mediik.uz/payment/return
    parsed = urlparse(base)
    extra = {"payment_id": str(payment.id), "status": status}
    query = dict(parse_qsl(parsed.query))
    query.update(extra)
    return urlunparse(parsed._replace(query=urlencode(query)))


class BasePaymentProvider(ABC):
    """Checkout URL generatori. Webhook handling paytechuz tomonida."""

    name: str = ""

    @abstractmethod
    def create_payment(
        self, payment: "Payment", return_url: str | None = None
    ) -> str:
        """Foydalanuvchini yo'naltirish uchun checkout URL qaytaradi.

        Args:
            payment: app.payments.models.Payment instance — paytechuz uchun
                ACCOUNT_MODEL bo'lib xizmat qiladi (account_id = payment.id).
            return_url: muvaffaqiyatli to'lovdan keyin user qaytadigan URL.

        Returns:
            Provider'ning checkout sahifasi URL'i.
        """
