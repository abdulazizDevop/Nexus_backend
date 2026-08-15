from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from app.users.models import Patient
from core.i18n import pick_translation


def _autofill_patient_profile(instance, user_field="user"):
    """user_id'dan Patient profilni avtomatik to'ldiradi."""
    user_id = getattr(instance, f"{user_field}_id", None)
    if user_id and not instance.patient_profile_id:
        patient_profile, _ = Patient.objects.get_or_create(user_id=user_id)
        instance.patient_profile = patient_profile
