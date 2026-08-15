from django.db import migrations


def backfill_specialties(apps, schema_editor):
    """Mavjud doctorlarning bitta `specialty`sini `specialties` M2M ga ko'chiradi."""
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")
    for dp in DoctorProfile.objects.filter(specialty__isnull=False).only(
        "id", "specialty_id"
    ):
        dp.specialties.add(dp.specialty_id)


def reverse(apps, schema_editor):
    # M2M ni tozalash shart emas (specialty FK saqlanib qoladi).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("doctors", "0013_doctorprofile_specialties_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_specialties, reverse),
    ]
