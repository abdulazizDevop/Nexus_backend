"""Existing Appointment row'lariga Patient profile bog'laydi.

Har Appointment.patient (User FK) → Patient (user=appointment.patient).
Idempotent — qaytadan ishlatish xavfsiz (faqat null patient_profile'larni to'ldiradi).
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Appointment = apps.get_model("meetings", "Appointment")
    Patient = apps.get_model("users", "Patient")

    filled = 0
    for appt in Appointment.objects.filter(patient_profile__isnull=True).only(
        "id", "patient_id"
    ):
        patient_profile, _ = Patient.objects.get_or_create(user_id=appt.patient_id)
        appt.patient_profile_id = patient_profile.id
        appt.save(update_fields=["patient_profile"])
        filled += 1
    print(f"  → Appointment.patient_profile backfilled: {filled}")


def reverse_backfill(apps, schema_editor):
    Appointment = apps.get_model("meetings", "Appointment")
    Appointment.objects.update(patient_profile=None)


class Migration(migrations.Migration):

    dependencies = [
        ("meetings", "0003_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
