"""Request-scoped logging context + access logs.

`RequestContextMiddleware` har HTTP so'rov uchun:

1. `X-Request-ID` header o'qiydi (yoki yangi UUID generatsiya qiladi) va
   contextvar ga set qiladi. Shu request ichida chaqirilgan har bir logda
   avtomatik `request_id` maydoni paydo bo'ladi.

2. Javobga ham `X-Request-ID` header qo'shadi — frontend/mobile app shu ID ni
   Sentry'ga yoki support tickerga biriktirishi mumkin. Better Stack'da shu
   ID bilan butun request'ning log oqimini tiklab olsa bo'ladi.

3. Javob yakunida access log yozadi: method, path, status_code, duration_ms,
   user_id, user_role. `health` va static endpointlar uchun yozilmaydi
   (chunki Better Stack uptime monitor ularni har 30s tekshiradi —
   shovqin bo'lmasligi uchun).

4. Agar `sentry_sdk` o'rnatilgan bo'lsa, `request_id` ni Sentry tag sifatida
   qo'shadi — shunday qilib Sentry'dagi errorni Better Stack loglari bilan
   oson bog'lash mumkin.
"""

from __future__ import annotations

import logging
import time
import uuid

from core.logging import (
    request_id_ctx,
    user_id_ctx,
    user_role_ctx,
)

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

logger = logging.getLogger("mediik.request")

# Access log yozilmaydi shu prefikslardan boshlangan path'lar uchun
_SKIP_ACCESS_LOG_PREFIXES = (
    "/health",
    "/static",
    "/media",
    "/favicon",
)


class RequestContextMiddleware:
    """HTTP request uchun log kontekstini o'rnatadi va access log yozadi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        rid_token = request_id_ctx.set(request_id)
        user_id_ctx.set(None)
        user_role_ctx.set(None)

        # Sentry bilan bog'lash (ixtiyoriy — o'rnatilmagan bo'lsa skip)
        if sentry_sdk is not None:
            sentry_sdk.set_tag("request_id", request_id)

        start = time.perf_counter()
        response = None
        try:
            response = self.get_response(request)
            return response
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "unhandled exception in request",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        finally:
            # DRF auth view ichida ishlaydi, shuning uchun request.user ni
            # get_response dan keyin o'qiymiz — endi autentifikatsiya tugagan.
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                user_id_ctx.set(getattr(user, "id", None))
                user_role_ctx.set(getattr(user, "role", None))

            if response is not None:
                response["X-Request-ID"] = request_id

                if not request.path.startswith(_SKIP_ACCESS_LOG_PREFIXES):
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    logger.info(
                        "%s %s %s",
                        request.method,
                        request.path,
                        response.status_code,
                        extra={
                            "method": request.method,
                            "path": request.path,
                            "status_code": response.status_code,
                            "duration_ms": duration_ms,
                        },
                    )

            # Contextvar'larni tozalash. request_id faqat shu yerda set
            # qilinadi — reset(token) to'g'ri ishlaydi. user_id/user_role esa
            # access log uchun finally ichida qayta set qilinadi, shuning uchun
            # eskirgan token bilan reset() qilish noto'g'ri — to'g'ridan-to'g'ri
            # None'ga qaytaramiz.
            request_id_ctx.reset(rid_token)
            user_id_ctx.set(None)
            user_role_ctx.set(None)
