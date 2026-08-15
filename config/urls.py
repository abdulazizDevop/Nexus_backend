# from django.contrib import admin
import redis as redis_lib
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from app.appinfo.views import MobileInfoView
from core.views import translate_view


def _safe_check(fn) -> bool:
    """Tekshiruvni xavfsiz bajaradi — istisno bo'lsa False qaytaradi."""
    try:
        fn()
        return True
    except Exception:
        return False


def _check_celery() -> bool:
    """Celery worker holati. Natijani 30s cache qiladi — har health so'rovida
    broker'ga blocking RPC yubormaslik uchun (autentifikatsiyasiz endpoint
    DoS amplifikatsiyasini oldini oladi)."""
    cached = cache.get("health:celery")
    if cached is not None:
        return cached

    def _inspect():
        from config.celery import app as celery_app

        insp = celery_app.control.inspect(timeout=2.0)
        if not insp.active_queues():
            raise RuntimeError("no active queues")

    ok = _safe_check(_inspect)
    cache.set("health:celery", ok, 30)
    return ok


@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([AllowAny])
@renderer_classes([JSONRenderer])
def root(request):
    return Response(
        {
            "status": "success",
            "message": "Welcome to Mediik API",
            "data": {
                "docs": {
                    "swagger": "/docs/",
                    "redoc": "/redoc/",
                    "schema": "/schema/",
                }
            },
        }
    )


@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([AllowAny])
@renderer_classes([JSONRenderer])
def health(request):
    """Server holati — monitoring uchun"""

    def _check_redis():
        redis_lib.from_url(settings.CELERY_BROKER_URL).ping()

    checks = {
        "api": True,
        "db": _safe_check(connection.ensure_connection),
        "redis": _safe_check(_check_redis),
        "celery": _check_celery(),
    }

    all_ok = all(checks.values())
    return Response(
        {"status": "healthy" if all_ok else "degraded", "checks": checks},
        status=200 if all_ok else 503,
    )


urlpatterns = [
    path("", root, name="root"),
    path("health/", health, name="health"),
    # Mobil — versiya/yangilanish ma'lumoti (login shart emas, /api/v1/ emas)
    path("info/mobile/", MobileInfoView.as_view(), name="mobile-info"),
    # path("__mediik__/", admin.site.urls),
    # API v1
    path("api/v1/auth/", include("app.auth.urls")),
    path("api/v1/users/", include("app.users.urls")),
    path("api/v1/doctors/", include("app.doctors.urls")),
    path("api/v1/meetings/", include("app.meetings.urls")),
    path("api/v1/treatments/", include("app.treatment.urls")),
    path("api/v1/feedbacks/", include("app.feedbacks.urls")),
    path("api/v1/packages/", include("app.health_packages.urls")),
    path("api/v1/", include("app.guides.urls")),
    path("api/v1/", include("app.appinfo.urls")),
    path("api/v1/", include("app.analytics.urls")),
    path("api/v1/payments/", include("app.payments.urls")),
    path("api/v1/chat/", include("app.chat.urls")),
    path("api/v1/medical/", include("app.medical.urls")),
    path("api/v1/notifications/", include("app.notifications.urls")),
    path("api/v1/diet/", include("app.diet_ai.urls")),
    path("api/v1/health-ai/", include("app.health_ai.urls")),
    path("api/v1/family/", include("app.family.urls")),
    path("api/v1/tracking-ai/", include("app.tracking_ai.urls")),
    path("api/v1/pharmacy/", include("app.pharmacy.urls")),
    path("api/v1/voice/", include("app.voice_ai.urls")),
    path("api/v1/translate/", translate_view, name="translate"),
    # Docs
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
