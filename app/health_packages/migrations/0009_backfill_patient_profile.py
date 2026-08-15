"""HealthIndicator va DailySituationCheckup row'lari uchun patient_profile backfill."""

from django.db import migrations


def backfill(apps, schema_editor):
    DailySituationCheckup = apps.get_model("health_packages", "DailySituationCheckup")
    HealthIndicator = apps.get_model("health_packages", "HealthIndicator")
    Patient = apps.get_model("users", "Patient")

    checkup_filled = 0
    for c in DailySituationCheckup.objects.filter(
        patient_profile__isnull=True
    ).only("id", "user_id"):
        patient_profile, _ = Patient.objects.get_or_create(user_id=c.user_id)
        c.patient_profile_id = patient_profile.id
        c.save(update_fields=["patient_profile"])
        checkup_filled += 1

    indicator_filled = 0
    for i in HealthIndicator.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        patient_profile, _ = Patient.objects.get_or_create(user_id=i.user_id)
        i.patient_profile_id = patient_profile.id
        i.save(update_fields=["patient_profile"])
        indicator_filled += 1

    print(
        f"  → DailySituationCheckup: {checkup_filled}, "
        f"HealthIndicator: {indicator_filled}"
    )


def reverse_backfill(apps, schema_editor):
    DailySituationCheckup = apps.get_model("health_packages", "DailySituationCheckup")
    HealthIndicator = apps.get_model("health_packages", "HealthIndicator")
    DailySituationCheckup.objects.update(patient_profile=None)
    HealthIndicator.objects.update(patient_profile=None)


class Migration(migrations.Migration):

    dependencies = [
        ("health_packages", "0008_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
