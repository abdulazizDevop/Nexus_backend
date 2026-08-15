"""DoctorPatient.patient_profile backfill."""

from django.db import migrations


def backfill(apps, schema_editor):
    DoctorPatient = apps.get_model("doctors", "DoctorPatient")
    Patient = apps.get_model("users", "Patient")

    filled = 0
    for dp in DoctorPatient.objects.filter(patient_profile__isnull=True).only(
        "id", "patient_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=dp.patient_id)
        dp.patient_profile_id = pp.id
        dp.save(update_fields=["patient_profile"])
        filled += 1
    print(f"  → DoctorPatient.patient_profile: {filled}")


def reverse_backfill(apps, schema_editor):
    apps.get_model("doctors", "DoctorPatient").objects.update(patient_profile=None)


class Migration(migrations.Migration):
    dependencies = [
        ("doctors", "0009_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
