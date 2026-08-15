import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsSuperOrSimpleAdmin, get_token_scope

from ..models import DeviceToken, Notification
from ..serializers import (
    DeviceTokenSerializer,
    MarkReadSerializer,
    NotificationSerializer,
)
from ..tasks import _do_broadcast, run_admin_broadcast

User = get_user_model()

logger = logging.getLogger(__name__)


_BOOL_QS = {"true": True, "false": False}

# Token churn limiti — bitta (user, app_scope, token_type) bo'yicha saqlanadigan
# eng so'nggi token soni. iOS reinstall'da IDFV (device_id) o'zgaradi → har qayta
# o'rnatish yangi token qatori yaratadi. Eski tokenlar silent push'ni behuda
# sekinlashtiradi va iOS background throttle'ni og'irlashtiradi.
MAX_TOKENS_PER_SCOPE = 3


def _parse_user_ids(raw) -> list[int] | None:
    """Query-string yoki list'dan user_ids ni xavfsiz parse qiladi.

    preview (querystring) va send (ListField) bir xil natija bersin uchun
    yagona parse yo'li.
    """
    if not raw:
        return None
    if isinstance(raw, str):
        return [int(x) for x in raw.split(",") if x.strip().isdigit()] or None
    return [int(x) for x in raw] or None


def _broadcast_targets_qs(user_ids: list[int] | None, role: str):
    """Broadcast filter — aniq user_ids yoki role bo'yicha aktiv userlar.

    Aniq `user_ids` (picker'dan tanlangan) — role filtri YO'Q: admin kimni tanlasa
    o'shanga yuboriladi (test/admin akkauntlar ham kiradi). Bulk (all/patient/doctor)
    esa adminlarni chiqarib tashlaydi — ularga ommaviy push bormaydi.
    """
    if user_ids:
        return User.objects.filter(id__in=user_ids, is_active=True)
    if role == "all":
        return User.objects.filter(role__in=["patient", "doctor"], is_active=True)
    return User.objects.filter(role=role, is_active=True)


# Shu chegaragacha bo'lgan auditoriya — sinxron yuboriladi (admin push natijasini
# darhol ko'radi). Kattasi — async Celery (HTTP thread bloklanmasin).
_SYNC_BROADCAST_LIMIT = 50


def _broadcast_app_scope(role: str) -> str | None:
    """role'dan push app_scope: patient/doctor -> o'sha scope, all -> None.

    Cross-app leak'ni oldini olish uchun — role aniq bo'lsa faqat shu app
    tokenlariga push boradi (CLAUDE.md app_scope qoidasi)."""
    return role if role in ("patient", "doctor") else None
