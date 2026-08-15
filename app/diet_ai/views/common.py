"""Diet AI REST API views.

Endpointlar:
    Patient:
        GET    /diet/conversations/                — suhbatlar ro'yxati
        POST   /diet/conversations/                — yangi suhbat yaratish
        GET    /diet/conversations/{id}/           — suhbat + xabarlar
        DELETE /diet/conversations/{id}/           — arxivlash
        POST   /diet/conversations/{id}/messages/  — text xabar yuborish
        POST   /diet/upload-url/                   — ovqat rasmi uchun S3 URL
        POST   /diet/analyze-photo/                — rasm + text tahlil
        GET    /diet/usage-today/                  — bugungi limit holati
        GET    /diet/restrictions/                 — o'z cheklovlarini ko'rish

    Doctor:
        GET    /diet/patients/{patient_id}/restrictions/  — bemor cheklovlari
        POST   /diet/patients/{patient_id}/restrictions/  — cheklov qo'shish
        PATCH  /diet/restrictions/{id}/                   — yangilash
        DELETE /diet/restrictions/{id}/                   — o'chirish

    Admin:
        GET    /diet/admin/conversations/          — barcha suhbatlar
        GET    /diet/admin/conversations/{id}/     — istalgan suhbatni ko'rish
"""

import logging
import uuid
from datetime import date as date_cls, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.doctors.models import DoctorPatient
from app.health_packages.models import HealthIndicator
from app.treatment.models import DailyCalorieLimit
from core.i18n import get_request_lang
from core.permissions import IsAdmin, IsDoctor, IsPatient, IsVerifiedDoctor
from services.gemini import generate_text, generate_with_image
from services.storage import (
    download_file_bytes,
    ext_for_mime,
    generate_upload_url,
    head_object_or_none,
)

from .. import services
from ..guardrails import get_safety_response, is_dangerous
from ..models import (
    HAS_IMAGE,
    DietConversation,
    DietEntry,
    DietMessage,
    DietProfile,
    DietRestriction,
)
from ..prompts import (
    FOOD_ANALYSIS_SCHEMA,
    build_system_prompt,
    get_photo_analysis_prompt,
    get_text_analysis_prompt,
)
from ..serializers import (
    AnalyzePhotoSerializer,
    AnalyzeTextSerializer,
    ConfirmCaloriesResponseSerializer,
    ConfirmCaloriesSerializer,
    DailyUsageSerializer,
    DietConversationCreateSerializer,
    DietConversationDetailSerializer,
    DietConversationListSerializer,
    DietEntryIngredientsEditSerializer,
    DietEntrySerializer,
    DietMessageSerializer,
    DietProfileSerializer,
    DietProfileWriteSerializer,
    DietRestrictionSerializer,
    DietTargetsSerializer,
    ManualDietEntrySerializer,
    MessageFeedbackSerializer,
    PhotoUploadUrlSerializer,
    SendMessageSerializer,
)

logger = logging.getLogger(__name__)

# Gemini inline rasm chegarasi (model 20MB qabul qiladi, biz 10MB cheklaymiz).
DIET_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _limit_exceeded_response(limit_info, include_info: bool = False) -> Response:
    """Kunlik AI limit tugaganda 429 javobi (send_message + analyze-photo umumiy)."""
    body = {
        "detail": (
            f"Bugungi limit tugadi ({limit_info['limit']}/kun). "
            f"Pro obunaga o'ting yoki ertaga qaytib keling."
        )
    }
    if include_info:
        body["limit_info"] = limit_info
    return Response(body, status=status.HTTP_429_TOO_MANY_REQUESTS)


def _meal_type_from_now() -> str:
    """Joriy soatdan ovqatlanish mahalini taxminlaydi (meal_type berilmaganda)."""
    hour = timezone.localtime().hour
    if 5 <= hour < 11:
        return DietEntry.MealType.BREAKFAST
    if 11 <= hour < 16:
        return DietEntry.MealType.LUNCH
    if 16 <= hour < 22:
        return DietEntry.MealType.DINNER
    return DietEntry.MealType.SNACK


def _parse_query_date(request) -> tuple["date_cls | None", Response | None]:
    """?date= ni parse qiladi. Returns (target_date, error_response).

    date param yo'q bo'lsa (None, None). Noto'g'ri format bo'lsa (None, 400).
    """
    date_str = request.query_params.get("date")
    if not date_str:
        return None, None
    try:
        return date_cls.fromisoformat(date_str), None
    except ValueError:
        return None, Response(
            {"detail": "Noto'g'ri sana formati. YYYY-MM-DD ishlating."},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _assert_patient_connected(doctor_user, patient_id) -> tuple[bool, Response | None]:
    """Doctor → patient ACCEPTED bog'lanish tekshiruvi.

    Returns (ok, error_response). Doctor profilingiz yo'q yoki patient
    bog'lanmagan bo'lsa — (False, 404).
    """
    profile = getattr(doctor_user, "doctor_profile", None)
    if not profile:
        return False, Response(
            {"detail": "Bemor topilmadi yoki ruxsat yo'q."},
            status=status.HTTP_404_NOT_FOUND,
        )
    if not DoctorPatient.objects.filter(
        doctor=profile,
        patient_id=patient_id,
        status=DoctorPatient.Status.ACCEPTED,
    ).exists():
        return False, Response(
            {"detail": "Bemor topilmadi yoki ruxsat yo'q."},
            status=status.HTTP_404_NOT_FOUND,
        )
    return True, None


# --- PATIENT ---




def _parse_iso_date_param(value, field_name):
    """Query param sanasini YYYY-MM-DD sifatida parse qiladi.

    Noto'g'ri format bo'lsa DRF ValidationError (400) — DB'ga noto'g'ri
    literal yuborib 500 olishning oldini oladi.
    """
    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        raise ValidationError(
            {field_name: "Noto'g'ri sana formati. YYYY-MM-DD ishlating."}
        )


def _filter_diet_history_qs(qs, request):
    """?date=, ?from=, ?to=, yoki default oxirgi 30 kun bilan filtrlash.

    Har bir sana query param'i validatsiya qilinadi (noto'g'ri format → 400).
    """
    date = request.query_params.get("date")
    date_from = request.query_params.get("from")
    date_to = request.query_params.get("to")

    if date:
        return qs.filter(date=_parse_iso_date_param(date, "date"))
    if date_from or date_to:
        if date_from:
            qs = qs.filter(date__gte=_parse_iso_date_param(date_from, "from"))
        if date_to:
            qs = qs.filter(date__lte=_parse_iso_date_param(date_to, "to"))
        return qs
    return qs.filter(date__gte=timezone.localdate() - timedelta(days=30))


