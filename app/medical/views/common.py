import uuid
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.doctors.models import DoctorPatient
from app.notifications.models import Notification
from app.notifications.utils import notify_by_key
from core.i18n import normalize_translations, pick_for
from core.permissions import (
    IsDoctor,
    IsSuperOrSimpleAdmin,
    IsVerifiedDoctor,
    get_request_role,
)
from services.gemini import generate_with_audio
from services.storage import (
    download_file_bytes,
    ext_for_mime,
    generate_upload_url,
)

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
from ..serializers import (
    AnalysisCancelSerializer,
    AnalysisCreateSerializer,
    AnalysisDetailSerializer,
    AnalysisIndicatorSerializer,
    AnalysisListSerializer,
    AnalysisMarkSeenByDoctorResponseSerializer,
    AnalysisPreparationSerializer,
    AnalysisResultUploadUrlRequestSerializer,
    AnalysisResultUploadUrlResponseSerializer,
    AnalysisReviewSerializer,
    AnalysisSubmitSerializer,
    AnalysisTypeSerializer,
    AnalysisUpdateSerializer,
    AudioUploadUrlRequestSerializer,
    AudioUploadUrlResponseSerializer,
    MedicalCardSerializer,
    MedicalCardSummarySerializer,
    MedicalConditionSerializer,
    MedicalNoteAIDraftRequestSerializer,
    MedicalNoteAIDraftResponseSerializer,
    MedicalNoteImageUploadUrlRequestSerializer,
    MedicalNoteImageUploadUrlResponseSerializer,
    MedicalNoteSerializer,
    PatientAnalysisCreateSerializer,
    PatientAnalysisUploadUrlRequestSerializer,
    PatientAnalysisUploadUrlResponseSerializer,
)

User = get_user_model()


# --- Helper ---

# Presigned upload URL amal qilish muddati (sekund) — services.storage default ham 900.
UPLOAD_URL_EXPIRES_IN = 900


def build_upload_item(prefix, file_type, fallback_ext):
    """Bitta presigned upload element: unik key generatsiya + upload_url + expires_in.

    prefix oxirida "/" bo'lishi kerak (masalan f"medical-audio/{user_id}/").
    """
    ext = ext_for_mime(file_type, fallback=fallback_ext)
    file_key = f"{prefix}{uuid.uuid4().hex[:12]}.{ext}"
    return {
        "upload_url": generate_upload_url(file_key, file_type),
        "file_key": file_key,
        "expires_in": UPLOAD_URL_EXPIRES_IN,
    }


def accepted_patient_ids(profile):
    """Doctor profilining ACCEPTED bog'langan bemorlari user_id ro'yxati (queryset)."""
    return DoctorPatient.objects.filter(
        doctor=profile,
        status=DoctorPatient.Status.ACCEPTED,
    ).values_list("patient_id", flat=True)


def doctor_can_access_patient(user, patient_id):
    """Doctor shu bemoriga DoctorPatient orqali bog'langanmi?"""
    profile = getattr(user, "doctor_profile", None)
    if not profile:
        return False

    return DoctorPatient.objects.filter(
        doctor=profile,
        patient_id=patient_id,
        status=DoctorPatient.Status.ACCEPTED,
    ).exists()


def resolve_target_user(request, patient_id):
    """patient_id bo'yicha kim uchun ishlanayotganini aniqlaydi.

    - Bemor o'zi uchun ishlasa: patient_id None bo'lishi mumkin.
    - Doctor bemor uchun ishlasa: patient_id berilishi va bog'langan bo'lishi shart.

    Returns: (user, error_response) tuple.
    """
    if patient_id is None or str(patient_id) in ("me", str(request.user.id)):
        return request.user, None

    try:
        patient_id_int = int(str(patient_id).strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        return None, Response({"detail": "Noto'g'ri patient_id."}, status=400)

    if get_request_role(request) == "doctor":
        if not doctor_can_access_patient(request.user, patient_id_int):
            return None, Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404
            )
        try:
            target = User.objects.get(pk=patient_id_int)
        except User.DoesNotExist:
            return None, Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404
            )
        return target, None

    # Patient o'zidan boshqasiga so'rov berolmaydi
    if patient_id_int != request.user.id:
        return None, Response(
            {"detail": "Boshqa foydalanuvchi ma'lumotini ko'rolmaysiz."}, status=403
        )
    return request.user, None


# --- Medical Card ---


