"""Braslet sync eslatma yozuvlarini tozalash (type choice olib tashlandi)."""

from django.db import migrations


def forwards(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.filter(type="bracelet_sync_reminder").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0019_alter_notification_type"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
