"""Medical doctor_profile backfill (Card.updated_by, Condition.added_by, Note.created_by)."""

from django.db import migrations


def backfill(apps, schema_editor):
    MedicalCard = apps.get_model("medical", "MedicalCard")
    MedicalCondition = apps.get_model("medical", "MedicalCondition")
    MedicalNote = apps.get_model("medical", "MedicalNote")
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")

    counts = {"card": 0, "cond": 0, "note": 0}

    for c in MedicalCard.objects.filter(
        doctor_profile__isnull=True, updated_by__isnull=False
    ).only("id", "updated_by_id"):
        dp = DoctorProfile.objects.filter(user_id=c.updated_by_id).first()
        if dp:
            c.doctor_profile_id = dp.id
            c.save(update_fields=["doctor_profile"])
            counts["card"] += 1

    for c in MedicalCondition.objects.filter(
        doctor_profile__isnull=True, added_by__isnull=False
    ).only("id", "added_by_id"):
        dp = DoctorProfile.objects.filter(user_id=c.added_by_id).first()
        if dp:
            c.doctor_profile_id = dp.id
            c.save(update_fields=["doctor_profile"])
            counts["cond"] += 1

    for n in MedicalNote.objects.filter(
        doctor_profile__isnull=True, created_by__isnull=False
    ).only("id", "created_by_id"):
        dp = DoctorProfile.objects.filter(user_id=n.created_by_id).first()
        if dp:
            n.doctor_profile_id = dp.id
            n.save(update_fields=["doctor_profile"])
            counts["note"] += 1

    print(
        f"  → MedicalCard: {counts['card']}, Condition: {counts['cond']}, "
        f"Note: {counts['note']}"
    )


def reverse_backfill(apps, schema_editor):
    apps.get_model("medical", "MedicalCard").objects.update(doctor_profile=None)
    apps.get_model("medical", "MedicalCondition").objects.update(doctor_profile=None)
    apps.get_model("medical", "MedicalNote").objects.update(doctor_profile=None)


class Migration(migrations.Migration):
    dependencies = [
        ("medical", "0004_add_doctor_profile"),
        ("doctors", "0010_backfill_doctorpatient_patient_profile"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
