"""HealthIndicatorType.system_key — Diet AI macros uchun stable identifier.

Diet AI 4 ta macro turini (kaloriya/uglevod/oqsil/yog') JSON name string'i
orqali topardi — bu `name__iexact` bilan JSONField'ga ishlamasdi. Endi
`system_key` orqali toparadi.

Dev/prod DB'da eski buzilgan `get_macros_types` har Diet AI chaqirilganda
yangi `HealthIndicatorType` yozuvi yaratgan bo'lishi mumkin (chunki filter
hech qachon mos kelmagan). Shu sababli macro nomi (Kaloriya, Uglevod, ...)
ga teng BIR NECHTA dublikat yozuv bo'lishi mumkin. Migration ularni eng
eski yozuvga konsolidatsiya qiladi (HealthIndicator qiymatlari summalab,
keyin dublikatlar o'chiriladi).
"""

from collections import defaultdict
from decimal import Decimal

from django.db import migrations, models


SYSTEM_KEY_MAP = {
    "Kaloriya": "calories",
    "Uglevod": "carbs",
    "Oqsil": "protein",
    "Yog'": "fat",
}


def _extract_uz(name) -> str:
    """JSONField yoki string'dan uz qiymatni ajratib oladi."""
    if isinstance(name, dict):
        return name.get("uz", "")
    if isinstance(name, str):
        return name
    return ""


def backfill_system_key(apps, schema_editor):
    HealthIndicatorType = apps.get_model("health_packages", "HealthIndicatorType")
    HealthIndicator = apps.get_model("health_packages", "HealthIndicator")

    # Macro nomi → barcha mos yozuvlar (eski-yangi tartibda)
    rows_by_uz = defaultdict(list)
    for obj in HealthIndicatorType.objects.all().order_by("id"):
        uz = _extract_uz(obj.name)
        if uz in SYSTEM_KEY_MAP:
            rows_by_uz[uz].append(obj)

    for uz, rows in rows_by_uz.items():
        canonical = rows[0]
        duplicates = rows[1:]
        dup_ids = [d.id for d in duplicates]

        # Dublikatlar HealthIndicator yozuvlarini canonical'ga ko'chirish.
        # unique_together = (user, indicator_type, date) — agar canonical'da
        # shu (user, date) allaqachon bor bo'lsa, qiymatlarni summalab birlashtiramiz.
        if dup_ids:
            for ind in HealthIndicator.objects.filter(indicator_type_id__in=dup_ids):
                existing = HealthIndicator.objects.filter(
                    user_id=ind.user_id,
                    indicator_type_id=canonical.id,
                    date=ind.date,
                ).first()
                if existing:
                    existing.value = (existing.value or Decimal(0)) + (
                        ind.value or Decimal(0)
                    )
                    if (
                        ind.value_secondary is not None
                        and existing.value_secondary is None
                    ):
                        existing.value_secondary = ind.value_secondary
                    existing.save(update_fields=["value", "value_secondary"])
                    ind.delete()
                else:
                    ind.indicator_type_id = canonical.id
                    ind.save(update_fields=["indicator_type"])

            # Dublikat HealthIndicatorType yozuvlarini o'chirish (CASCADE bilan
            # qolgan referenc'lar avtomatik tozalanadi, lekin biz yuqorida
            # hammasini ko'chirib bo'ldik).
            HealthIndicatorType.objects.filter(id__in=dup_ids).delete()

        # Canonical row'ga system_key qo'yish
        canonical.system_key = SYSTEM_KEY_MAP[uz]
        canonical.save(update_fields=["system_key"])


def reverse_system_key(apps, schema_editor):
    """Reverse: system_key NULL qaytaradi (field o'chmasdan oldin).

    Konsolidatsiya teskariga ishlamaydi — dublikat yozuvlar tiklanmaydi.
    """
    Model = apps.get_model("health_packages", "HealthIndicatorType")
    Model.objects.update(system_key=None)


class Migration(migrations.Migration):
    # PostgreSQL: AddField (CREATE UNIQUE INDEX) + RunPython (CASCADE DELETE)
    # bitta tranzaksiyada `pending trigger events` xatosini beradi. 0010 kabi
    # `atomic = False` har step alohida tranzaksiyada ishlashini ta'minlaydi.
    atomic = False

    dependencies = [
        ("health_packages", "0010_indicatortype_i18n"),
    ]

    operations = [
        migrations.AddField(
            model_name="healthindicatortype",
            name="system_key",
            field=models.CharField(
                blank=True,
                help_text="Diet AI macros uchun stable ID. Oddiy turlarda bo'sh.",
                max_length=20,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(backfill_system_key, reverse_system_key),
    ]
