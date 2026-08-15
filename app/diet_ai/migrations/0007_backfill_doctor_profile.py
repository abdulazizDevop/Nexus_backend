"""DietRestriction.doctor_profile backfill (User → DoctorProfile if user is a doctor)."""

from django.db import migrations


def backfill(apps, schema_editor):
    DietRestriction = apps.get_model("diet_ai", "DietRestriction")
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")

    filled = 0
    for r in DietRestriction.objects.filter(
        doctor_profile__isnull=True, doctor__isnull=False
    ).only("id", "doctor_id"):
        dp = DoctorProfile.objects.filter(user_id=r.doctor_id).first()
        if dp:
            r.doctor_profile_id = dp.id
            r.save(update_fields=["doctor_profile"])
            filled += 1
    print(f"  → DietRestriction.doctor_profile: {filled}")


def reverse_backfill(apps, schema_editor):
    apps.get_model("diet_ai", "DietRestriction").objects.update(doctor_profile=None)


class Migration(migrations.Migration):
    dependencies = [
        ("diet_ai", "0006_add_doctor_profile"),
        ("doctors", "0010_backfill_doctorpatient_patient_profile"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
