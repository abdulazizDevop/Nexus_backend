"""Treatment va DailyCalorieLimit row'lari uchun patient_profile backfill.

Idempotent — null patient_profile'larni Patient (user=row.user) bilan to'ldiradi.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Treatment = apps.get_model("treatment", "Treatment")
    DailyCalorieLimit = apps.get_model("treatment", "DailyCalorieLimit")
    Patient = apps.get_model("users", "Patient")

    treatment_filled = 0
    for t in Treatment.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        patient_profile, _ = Patient.objects.get_or_create(user_id=t.user_id)
        t.patient_profile_id = patient_profile.id
        t.save(update_fields=["patient_profile"])
        treatment_filled += 1

    cl_filled = 0
    for cl in DailyCalorieLimit.objects.filter(
        patient_profile__isnull=True
    ).only("id", "patient_id"):
        patient_profile, _ = Patient.objects.get_or_create(user_id=cl.patient_id)
        cl.patient_profile_id = patient_profile.id
        cl.save(update_fields=["patient_profile"])
        cl_filled += 1

    print(
        f"  → Treatment.patient_profile: {treatment_filled}, "
        f"DailyCalorieLimit.patient_profile: {cl_filled}"
    )


def reverse_backfill(apps, schema_editor):
    Treatment = apps.get_model("treatment", "Treatment")
    DailyCalorieLimit = apps.get_model("treatment", "DailyCalorieLimit")
    Treatment.objects.update(patient_profile=None)
    DailyCalorieLimit.objects.update(patient_profile=None)


class Migration(migrations.Migration):

    dependencies = [
        ("treatment", "0006_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
