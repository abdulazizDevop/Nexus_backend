from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.i18n import pick_for
from core.serializers import TranslatableFieldsMixin
from services.storage import generate_download_url

from ..models import (
    Analysis,
    AnalysisFile,
    AnalysisIndicator,
    AnalysisPreparation,
    AnalysisResult,
    AnalysisResultValue,
    AnalysisType,
    MedicalCard,
    MedicalCondition,
    MedicalNote,
    MedicalNoteImage,
)


def _signed_download(key, expiry=3600):
    """Bunny CDN signed URL — key bo'lmasa None."""
    return generate_download_url(key, expiry_seconds=expiry) if key else None


def _days_left(analysis):
    """deadline_at gacha qolgan kunlar (manfiy bo'lmaydi); deadline yo'q → None."""
    if not analysis.deadline_at:
        return None
    delta = analysis.deadline_at - timezone.now()
    return max(0, delta.days)


def _compute_ui_status(analysis):
    """UI badge code'i (frontend mapping uchun stable):

    cancelled | prescribed | sent | viewed | commented

    Progression: prescribed → sent → viewed → commented
      - sent      = bemor topshirdi, doctor hali ochmagan (YUBORILDI)
      - viewed    = doctor ochib ko'rdi, sharh hali yo'q (KO'RILDI)
      - commented = doctor sharh yozdi (SHARH KELDI)
    """
    if analysis.status == Analysis.Status.CANCELLED:
        return "cancelled"
    if analysis.status == Analysis.Status.PRESCRIBED:
        return "prescribed"
    if analysis.status == Analysis.Status.REVIEWED:
        return "commented"
    if analysis.status == Analysis.Status.SUBMITTED:
        return "viewed" if analysis.doctor_viewed_at else "sent"
    return analysis.status


def ui_status_q(code):
    """ui_status badge kodi → DB filter (Q). _compute_ui_status'ning teskari yo'li.

    Noma'lum kod uchun None qaytaradi (filter qo'llanmaydi).
    """
    mapping = {
        "cancelled": Q(status=Analysis.Status.CANCELLED),
        "prescribed": Q(status=Analysis.Status.PRESCRIBED),
        "commented": Q(status=Analysis.Status.REVIEWED),
        # SUBMITTED + doctor_viewed_at IS NULL → "sent" (YUBORILDI)
        "sent": Q(status=Analysis.Status.SUBMITTED, doctor_viewed_at__isnull=True),
        # SUBMITTED + doctor_viewed_at IS NOT NULL → "viewed" (KO'RILDI)
        "viewed": Q(status=Analysis.Status.SUBMITTED, doctor_viewed_at__isnull=False),
    }
    return mapping.get(code)


def _doctor_brief(user):
    """User → {user_id, full_name, specialty, avatar_url} mapping (doctor uchun).

    User.avatar — CharField (S3 key), `.url` mavjud emas → Bunny CDN signed URL.
    """
    if not user:
        return None
    profile = getattr(user, "doctor_profile", None)
    specialty = None
    if profile and getattr(profile, "specialty_id", None):
        specialty = profile.specialty.name

    return {
        "user_id": user.id,
        "doctor_profile_id": profile.id if profile else None,
        "full_name": user.full_name or user.phone,
        "specialty": specialty,
        "avatar_url": _signed_download(user.avatar),
    }
