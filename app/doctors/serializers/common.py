import logging

from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.i18n import pick_for
from core.serializers import TranslatableFieldsMixin
from services.storage import generate_download_url

from ..models import (
    DoctorCertificate,
    DoctorPatient,
    DoctorProfile,
    Slot,
    Specialty,
)

User = get_user_model()
logger = logging.getLogger("mediik.doctors")


def _media_url(key):
    """S3 key ni Bunny CDN signed URL ga aylantiradi."""
    return generate_download_url(key) if key else None



class _TariffMixin:
    """tariff_status / tariff_days_left / tariff_expires_at / tariff_name uchun
    umumiy SerializerMethodField helperlari.

    Subclass `_purchase(obj)` metodini ta'minlasin — qaysi context kalitidan
    DoctorTariffPurchase qaytarish.
    """

    def _purchase(self, obj):
        raise NotImplementedError

    def get_tariff_status(self, obj):
        p = self._purchase(obj)
        if not p:
            return "none"
        return "active" if p.is_active else "expired"

    def get_tariff_days_left(self, obj):
        p = self._purchase(obj)
        if not p:
            return None
        delta = (p.expires_at - timezone.now()).days
        return delta if delta > 0 else 0

    def get_tariff_expires_at(self, obj):
        p = self._purchase(obj)
        return p.expires_at.isoformat() if p else None

    def get_tariff_name(self, obj):
        p = self._purchase(obj)
        if not p:
            return None
        if p.tariff_id and p.tariff:
            return pick_for(self.context, p.tariff.name)
        # Snapshot ham translatable dict (purchase vaqtidagi)
        snapshot_name = (p.tariff_snapshot or {}).get("name")
        return pick_for(self.context, snapshot_name) if snapshot_name else None


