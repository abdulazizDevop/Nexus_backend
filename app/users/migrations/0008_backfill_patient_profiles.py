"""Har mavjud user uchun Patient profile yaratadi.

Idempotent — qaytadan ishlatish xavfsiz (get_or_create).
Reverse — barcha Patient row'larni o'chiradi (data only, model saqlanadi).
"""

from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("users", "User")
    Patient = apps.get_model("users", "Patient")

    created = 0
    for user in User.objects.all().only("id"):
        _, was_created = Patient.objects.get_or_create(user_id=user.id)
        if was_created:
            created += 1
    print(f"  → Patient profiles created: {created}")


def reverse_backfill(apps, schema_editor):
    Patient = apps.get_model("users", "Patient")
    Patient.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0007_patient_profile"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
