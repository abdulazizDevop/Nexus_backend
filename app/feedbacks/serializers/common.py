from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from app.meetings.models import Appointment
from services.storage import generate_download_url

from ..models import (
    CRITICAL_MAX_RATING,
    POSITIVE_MIN_RATING,
    REVIEW_COOLDOWN_DAYS,
    Review,
    ReviewTag,
)
