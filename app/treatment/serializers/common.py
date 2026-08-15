from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from app.doctors.models import DoctorPatient

from ..models import DailyCalorieLimit, Treatment, TreatmentLog


User = get_user_model()


def _validate_doctor_patient_link(patient_id, context):
    """Patient mavjudligini va doctor↔patient bog'lanish (ACCEPTED) borligini tekshiradi.

    Doctor o'z bemori uchungina muolaja yoki kaloriya chegarasi yozishi kerak.
    Doctor profile yo'q yoki request yo'q bo'lsa — faqat user mavjudligini tekshiradi.
    """
    if not User.objects.filter(id=patient_id).exists():
        raise serializers.ValidationError("Foydalanuvchi topilmadi.")

    request = context.get("request")
    if not (request and request.user.is_authenticated):
        return patient_id

    profile = getattr(request.user, "doctor_profile", None)
    if not profile:
        return patient_id

    connected = DoctorPatient.objects.filter(
        doctor=profile,
        patient_id=patient_id,
        status=DoctorPatient.Status.ACCEPTED,
    ).exists()
    if not connected:
        raise serializers.ValidationError("Bu bemor sizning ro'yxatingizda yo'q.")
    return patient_id
