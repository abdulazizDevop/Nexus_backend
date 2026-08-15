"""Review patient_profile backfill."""

from django.db import migrations


def backfill(apps, schema_editor):
    Review = apps.get_model("feedbacks", "Review")
    Patient = apps.get_model("users", "Patient")

    filled = 0
    for r in Review.objects.filter(patient_profile__isnull=True).only(
        "id", "patient_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=r.patient_id)
        r.patient_profile_id = pp.id
        r.save(update_fields=["patient_profile"])
        filled += 1
    print(f"  → Review.patient_profile: {filled}")


def reverse_backfill(apps, schema_editor):
    apps.get_model("feedbacks", "Review").objects.update(patient_profile=None)


class Migration(migrations.Migration):
    dependencies = [
        ("feedbacks", "0003_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
