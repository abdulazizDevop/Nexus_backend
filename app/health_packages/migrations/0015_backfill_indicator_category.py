"""Mavjud ko'rsatkich turlariga `category` + `manual_entry` backfill.

Spec: indicator_types_category_spec.md §4.2. Kategoriya kodda taxmin qilinmaydi —
shu yerda system_key bo'yicha bir marta to'ldiriladi, keyin admin UI'da boshqaradi.

  • DIET (calories/carbs/protein/fat)              → category=diet,     manual_entry=False
  • WEARABLE (SDK o'lchaydigan 9 ta)               → category=wearable
  • qolgani (blood_pressure/hrv/weight/glucose/    → category=manual
    hba1c + system_key'siz oddiy turlar)
  • CUMULATIVE braslet turlari (kunlik yig'indi)   → manual_entry=False (ikki marta
    sanalmasin); qolgan wearable/manual            → manual_entry=True
"""

from django.db import migrations

# SDK (Veepoo) haqiqatan o'lchaydigan turlar — spec §6. blood_pressure/hrv SDK
# o'lchamaydi → manual. Yangi tur qo'shilsa admin category'ni o'zi tanlaydi.
WEARABLE = {
    "heart_rate", "steps", "spo2", "stress", "temperature",
    "distance_m", "calories_burned", "sleep", "met",
}
DIET = {"calories", "carbs", "protein", "fat"}
# Kunlik yig'indi (kumulyativ) — qo'lda kiritish braslet bilan ikki marta sanaydi.
CUMULATIVE = {"steps", "distance_m", "calories_burned", "sleep", "met"}


def backfill(apps, schema_editor):
    Type = apps.get_model("health_packages", "HealthIndicatorType")
    for t in Type.objects.all():
        if t.system_key in DIET:
            t.category = "diet"
        elif t.system_key in WEARABLE:
            t.category = "wearable"
        else:
            t.category = "manual"
        t.manual_entry = (t.category != "diet") and (t.system_key not in CUMULATIVE)
        t.save(update_fields=["category", "manual_entry"])


class Migration(migrations.Migration):
    dependencies = [
        ("health_packages", "0014_healthindicatortype_category_and_more"),
    ]
    operations = [
        # Reverse — no-op (0014 reverse ustunlarni o'chiradi)
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
