"""Diet AI Pro feature flag qo'shish."""

from django.db import migrations


def add_diet_ai_flag(apps, schema_editor):
    ProFeatureFlag = apps.get_model("payments", "ProFeatureFlag")
    ProFeatureFlag.objects.update_or_create(
        key="unlimited_diet_ai",
        defaults={
            "label": "Cheksiz parhez maslahatchi (AI)",
            "icon": "🥗",
            "is_active": True,
        },
    )


def remove_diet_ai_flag(apps, schema_editor):
    ProFeatureFlag = apps.get_model("payments", "ProFeatureFlag")
    ProFeatureFlag.objects.filter(key="unlimited_diet_ai").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0002_doctortariff_is_popular"),
    ]

    operations = [
        migrations.RunPython(add_diet_ai_flag, remove_diet_ai_flag),
    ]
