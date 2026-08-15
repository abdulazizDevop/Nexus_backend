"""Treatment + DailyCalorieLimit doctor_profile backfill.

Existing rows: agar created_by/set_by foydalanuvchisida DoctorProfile bo'lsa —
shu profil bilan to'ldiriladi. Aks holda null qoladi (admin yoki patient self-add).
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Treatment = apps.get_model("treatment", "Treatment")
    DailyCalorieLimit = apps.get_model("treatment", "DailyCalorieLimit")
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")

    treatment_filled = 0
    for t in Treatment.objects.filter(
        doctor_profile__isnull=True, created_by__isnull=False
    ).only("id", "created_by_id"):
        dp = DoctorProfile.objects.filter(user_id=t.created_by_id).first()
        if dp:
            t.doctor_profile_id = dp.id
            t.save(update_fields=["doctor_profile"])
            treatment_filled += 1

    cl_filled = 0
    for cl in DailyCalorieLimit.objects.filter(
        doctor_profile__isnull=True, set_by__isnull=False
    ).only("id", "set_by_id"):
        dp = DoctorProfile.objects.filter(user_id=cl.set_by_id).first()
        if dp:
            cl.doctor_profile_id = dp.id
            cl.save(update_fields=["doctor_profile"])
            cl_filled += 1

    print(
        f"  → Treatment.doctor_profile: {treatment_filled}, "
        f"DailyCalorieLimit.doctor_profile: {cl_filled}"
    )


def reverse_backfill(apps, schema_editor):
    apps.get_model("treatment", "Treatment").objects.update(doctor_profile=None)
    apps.get_model("treatment", "DailyCalorieLimit").objects.update(
        doctor_profile=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("treatment", "0008_add_doctor_profile"),
        ("doctors", "0010_backfill_doctorpatient_patient_profile"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
