from datetime import datetime as dt, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.db.models import (
    Count,
    DateTimeField,
    Exists,
    F,
    IntegerField,
    Min,
    OuterRef,
    Q,
    Subquery,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.health_packages.models import DailySituationCheckup, HealthIndicator
from app.notifications.models import Notification
from app.notifications.tasks import notify_by_key_user
from app.payments.models import DoctorTariff, DoctorTariffPurchase
from app.treatment.models import Treatment, TreatmentLog
from core.i18n import get_request_lang, pick_translation
from core.permissions import (
    IsDoctor,
    IsSuperAdmin,
    IsSuperOrSimpleAdmin,
    IsVerifiedDoctor,
)
from services.storage import generate_certificate_key, generate_upload_url

from ..models import (
    DoctorCertificate,
    DoctorPatient,
    DoctorProfile,
    Slot,
    Specialty,
    patient_ids_by_doctor,
    patient_ids_for_doctor,
)
from ..serializers import (
    AddByPhoneSerializer,
    AdminSlotSerializer,
    DoctorCertificateSerializer,
    DoctorListSerializer,
    DoctorPatientSerializer,
    MarketplaceDoctorSerializer,
    DoctorProfileSerializer,
    DoctorProfileUpdateSerializer,
    PatientDetailSerializer,
    PatientWithHealthSerializer,
    SlotSerializer,
    SlotSyncRequestSerializer,
    SpecialtySerializer,
)

User = get_user_model()


# Slot generatsiyasi uchun chegaralar
SLOT_WINDOW_DAYS = 90
SLOT_MIN_MINUTES = 5
SLOT_MAX_MINUTES = 240


def _allowed_patient_ids(profile, user) -> set:
    """Doctor o'z bemorlari ID'larini qaytaradi (DoctorPatient ACCEPTED + referral)."""
    return patient_ids_for_doctor(profile)


def doctor_display_name(user) -> str:
    """Notification params uchun doctor ko'rsatiladigan nomi."""
    return f"Dr. {user.full_name}" if user and user.full_name else "Shifokor"


