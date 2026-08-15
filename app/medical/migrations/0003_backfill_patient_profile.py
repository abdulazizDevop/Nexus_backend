"""Medical app patient_profile backfill (MedicalCard, Condition, Note)."""

from django.db import migrations


def backfill(apps, schema_editor):
    MedicalCard = apps.get_model("medical", "MedicalCard")
    MedicalCondition = apps.get_model("medical", "MedicalCondition")
    MedicalNote = apps.get_model("medical", "MedicalNote")
    Patient = apps.get_model("users", "Patient")

    counts = {"card": 0, "condition": 0, "note": 0}

    for c in MedicalCard.objects.filter(patient_profile__isnull=True).only("id", "user_id"):
        pp, _ = Patient.objects.get_or_create(user_id=c.user_id)
        c.patient_profile_id = pp.id
        c.save(update_fields=["patient_profile"])
        counts["card"] += 1

    for c in MedicalCondition.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=c.user_id)
        c.patient_profile_id = pp.id
        c.save(update_fields=["patient_profile"])
        counts["condition"] += 1

    for n in MedicalNote.objects.filter(patient_profile__isnull=True).only("id", "user_id"):
        pp, _ = Patient.objects.get_or_create(user_id=n.user_id)
        n.patient_profile_id = pp.id
        n.save(update_fields=["patient_profile"])
        counts["note"] += 1

    print(
        f"  → MedicalCard: {counts['card']}, Condition: {counts['condition']}, "
        f"Note: {counts['note']}"
    )


def reverse_backfill(apps, schema_editor):
    apps.get_model("medical", "MedicalCard").objects.update(patient_profile=None)
    apps.get_model("medical", "MedicalCondition").objects.update(patient_profile=None)
    apps.get_model("medical", "MedicalNote").objects.update(patient_profile=None)


class Migration(migrations.Migration):
    dependencies = [
        ("medical", "0002_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
