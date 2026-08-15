"""Eski (app_scope=null) notification'larni ILOVA scope'iga backfill.

Faqat ANIQ bitta-ilovalik turlar. Aralash (chat/call/system/broadcast) turlar
null qoladi — barcha ilovada ko'rinaveradi (leak emas, ular haqiqatan umumiy).
"""

from django.db import migrations

# Faqat bemor ilovasida ko'rinishi kerak bo'lganlar
_PATIENT = [
    "treatment_reminder",
    "bracelet_sync_reminder",
    "calorie_limit",
    "review_reminder",
    "appointment_approved",
    "appointment_rejected",
    "offline_payment_confirmed",
    "offline_payment_rejected",
]

# Faqat doctor ilovasida ko'rinishi kerak bo'lganlar
_DOCTOR = [
    "appointment_created",
    "new_review",
    "tariff_approved",
    "tariff_rejected",
    "payout_completed",
    "payout_rejected",
    "offline_payment_request",
    "daily_ai_report",
]


def backfill(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.filter(type__in=_PATIENT, app_scope__isnull=True).update(
        app_scope="patient"
    )
    Notification.objects.filter(type__in=_DOCTOR, app_scope__isnull=True).update(
        app_scope="doctor"
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("notifications", "0015_notification_app_scope")]
    operations = [migrations.RunPython(backfill, noop)]
