"""Phase 2 — event middleware: har so'rovni feature'ga map qilib kunlik hisoblaydi.

Deploydan keyingi ANIQ (endpoint-darajali) faollikni yozadi — jumladan yozuv
yaratmaydigan "ochish/ko'rish" harakatlarini ham. Analitika hech qachon so'rovni
buzmasin — hamma narsa try/except ichida, javob har doim qaytadi.

DRF JWT autentifikatsiyasi view darajasida bo'ladi (request.user middleware'da
AnonymousUser). Shuning uchun mos feature-path'lardagina JWT'ni o'zimiz decode
qilamiz (ortiqcha ish faqat kuzatiladigan endpointlarda).
"""
import logging

from django.db.models import F
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication

from .registry import feature_for_path

logger = logging.getLogger(__name__)

_jwt = JWTAuthentication()


class FeatureUsageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._record(request, response)
        except Exception:
            # Analitika yozuvi hech qachon so'rovni buzmaydi (best-effort).
            logger.debug("feature usage record skipped", exc_info=True)
        return response

    def _record(self, request, response):
        if getattr(response, "status_code", 500) >= 400:
            return
        feature = feature_for_path(request.path)
        if not feature:
            return  # arzon gate — mos kelmasa umuman JWT decode qilmaymiz

        try:
            result = _jwt.authenticate(request)
        except Exception:
            return  # yaroqsiz/yo'q token — jim o'tkazamiz
        if not result:
            return
        user, token = result

        scope = None
        for claim in ("scope", "active_role"):
            try:
                scope = token[claim]
                break
            except (KeyError, TypeError):
                continue

        from .models import FeatureUsageDaily

        today = timezone.localdate()
        obj, created = FeatureUsageDaily.objects.get_or_create(
            user=user,
            feature=feature,
            date=today,
            defaults={"count": 1, "scope": scope},
        )
        if not created:
            FeatureUsageDaily.objects.filter(pk=obj.pk).update(count=F("count") + 1)
