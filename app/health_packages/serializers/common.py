from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from core.i18n import pick_for
from core.serializers import TranslatableFieldsMixin

from ..models import (
    DailySituationCheckup,
    HealthIndicator,
    HealthIndicatorType,
)

# recorded_at kelajakka bir oz tolerance (qurilma soati biroz oldinda bo'lsa).


_RECORDED_AT_FUTURE_TOLERANCE = timedelta(minutes=5)


def _validate_not_future(value):
    """recorded_at kelajak vaqtga bo'lmasligini tekshiradi (kichik tolerance bilan)."""
    if value and value > timezone.now() + _RECORDED_AT_FUTURE_TOLERANCE:
        raise serializers.ValidationError("recorded_at kelajak vaqtga bo'lishi mumkin emas.")
    return value
