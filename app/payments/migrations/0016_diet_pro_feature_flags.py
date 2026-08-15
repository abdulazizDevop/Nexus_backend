"""AI Parhez Pro feature flag'lari: meal_advice + haftalik progress."""

from django.db import migrations

FLAGS = [
    ("diet_meal_advice", "Har-mahal AI parhez tavsiyasi", "🍽️"),
    ("diet_weekly_report", "Haftalik AI parhez hisoboti", "📈"),
]


def add_flags(apps, schema_editor):
    ProFeatureFlag = apps.get_model("payments", "ProFeatureFlag")
    for order, (key, label, icon) in enumerate(FLAGS):
        ProFeatureFlag.objects.update_or_create(
            key=key,
            defaults={"label": label, "icon": icon, "is_active": True},
        )


def remove_flags(apps, schema_editor):
    ProFeatureFlag = apps.get_model("payments", "ProFeatureFlag")
    ProFeatureFlag.objects.filter(key__in=[k for k, _, _ in FLAGS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0015_doctorbalance_total_commission_paid_and_more"),
    ]

    operations = [
        migrations.RunPython(add_flags, remove_flags),
    ]
