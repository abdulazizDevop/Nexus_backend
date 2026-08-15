"""health_packages view'lari uchun umumiy helper'lar (bir necha submodul ishlatadi)."""

from collections import defaultdict

from app.doctors.models import DoctorPatient


def _doctor_can_access_patient(user, patient_id) -> bool:
    """Doctor shu bemoriga ACCEPTED holatda bog'langanmi?"""
    profile = getattr(user, "doctor_profile", None)
    if not profile:
        return False
    return DoctorPatient.objects.filter(
        doctor=profile,
        patient_id=patient_id,
        status=DoctorPatient.Status.ACCEPTED,
    ).exists()


def _group_by_date(rows) -> dict:
    """serializer.data ro'yxatini `date` maydoni bo'yicha guruhlaydi."""
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["date"]].append(row)
    return grouped
