"""Braslet olib tashlangandan keyingi data tozalash.

1. source='bracelet' o'lchovlar o'chiriladi — ularni yozadigan feature yo'q,
   ro'yxatlarda "egasiz" ko'rinib turmasin.
2. category='wearable' turlar 'manual'ga o'tkaziladi va manual_entry=True
   qilinadi — bemor endi qadam/uyqu kabi ko'rsatkichlarni qo'lda kiritadi
   (voice_ai/diet_ai/health_ai shu turlarga system_key orqali tayanadi,
   turlarning o'zi O'CHIRILMAYDI).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    HealthIndicator = apps.get_model("health_packages", "HealthIndicator")
    HealthIndicatorType = apps.get_model("health_packages", "HealthIndicatorType")

    HealthIndicator.objects.filter(source="bracelet").delete()
    HealthIndicatorType.objects.filter(category="wearable").update(
        category="manual", manual_entry=True
    )


class Migration(migrations.Migration):

    dependencies = [
        ("health_packages", "0017_alter_healthindicator_recorded_at_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
