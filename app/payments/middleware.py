"""To'lov demo-rejimi middleware'i.

PAYMENTS_ENABLED=False (default, demo) bo'lganda to'lov BOSHLAYDIGAN
endpointlarga yozuv so'rovlari 503 + tushunarli "bu demo" javobini oladi.
O'qish endpointlari (tarif ro'yxati, planlar, balans) ishlashda davom etadi —
UI to'liq ko'rinadi, faqat pul harakati o'chiq.
"""

from django.conf import settings
from django.http import JsonResponse

# To'lov boshlanish/qabul yo'llari (prefix bo'yicha, faqat yozuv metodlari).
_BLOCKED_PREFIXES = (
    "/api/v1/payments/pro/subscribe/",
    "/api/v1/payments/topup/",
    "/api/v1/payments/atmos/",
    "/api/v1/payments/offline/",
    "/api/v1/payments/webhook/",
    "/api/v1/payments/doctor-tariffs/",  # {id}/purchase/ shu prefix ostida
)
_WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class PaymentsDemoModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            not getattr(settings, "PAYMENTS_ENABLED", False)
            and request.method in _WRITE_METHODS
            and request.path.startswith(_BLOCKED_PREFIXES)
        ):
            return JsonResponse(
                {
                    "detail": (
                        "Bu demo versiya — to'lovlar hozircha ishlamaydi. "
                        "Barcha imkoniyatlar to'lovsiz ochiq."
                    ),
                    "code": "payments_demo_mode",
                },
                status=503,
            )
        return self.get_response(request)
