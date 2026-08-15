import functools
import logging
from datetime import date, datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from app.users.models import UserSettings
from core.i18n import pick_for
from services.storage import generate_download_url

User = get_user_model()
logger = logging.getLogger(__name__)


def _avatar_url(key):
    return generate_download_url(key) if key else None


# ─────────────────────────────────────────────────────────────────────────
# Full-info (admin "to'liq user ma'lumoti") — yordamchilar
# ─────────────────────────────────────────────────────────────────────────

# Har ro'yxat bo'limi shu miqdorda cheklanadi (admin panel — tez ochilishi uchun).
FULL_INFO_CAP = 30
ACTIVITY_CAP = 60


def _uname(u):
    """User → ko'rsatiladigan ism (ism bo'lmasa telefon)."""
    if not u:
        return None
    return u.full_name or u.phone


def _disp(obj, field):
    """`get_<field>_display()` bo'lsa uni, bo'lmasa xom qiymatni qaytaradi."""
    getter = getattr(obj, f"get_{field}_display", None)
    try:
        return getter() if getter else getattr(obj, field, None)
    except Exception:
        return getattr(obj, field, None)


def _iso(v):
    if v is None:
        return None
    try:
        return v.isoformat()
    except Exception:
        return None


def _aware(v):
    """date/datetime → timeline saralash uchun aware datetime."""
    try:
        if isinstance(v, datetime):
            return timezone.make_aware(v) if timezone.is_naive(v) else v
        if isinstance(v, date):
            return timezone.make_aware(datetime.combine(v, datetime.min.time()))
    except Exception:
        pass
    return timezone.make_aware(datetime(1970, 1, 1))


def _amt(v):
    """Decimal/None → string (JSON uchun)."""
    return str(v) if v is not None else None


def _safe_section(default_factory):
    """Bo'lim method'ini o'raydi — xato bo'lsa butun javob 500 bermaydi,
    faqat o'sha bo'lim default (bo'sh) qaytadi va log yoziladi."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, obj):
            try:
                return fn(self, obj)
            except Exception:
                logger.exception(
                    "full-info bo'limi '%s' user=%s uchun ishlamadi",
                    fn.__name__,
                    getattr(obj, "id", None),
                )
                return default_factory()

        return wrapper

    return deco


