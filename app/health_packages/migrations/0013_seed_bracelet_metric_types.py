"""Braslet metric turlarini DB'ga seed qilish (idempotent).

Oldingi versiyada bu ro'yxat `serializers.py` da hardcode bo'lgan
(`BRACELET_METRICS`). Endi haqiqat manbai — DB. Bu migration mavjud
yozuvlarni saqlaydi (`get_or_create` + `system_key` unique) va
yo'qlarini yaratadi.

`system_key` — Valdus SDK frontend tomonidan POST'da `metric` field bilan
jo'natiladigan stable identifier. Frontend yangi metric qo'shsa
(masalan `stress`), backend kodida o'zgarish kerak emas — admin DB'ga
yangi HealthIndicatorType qo'shsa kifoya. (Hozir bu migration orqali
14 ta standart turi seed qilinmoqda.)
"""

from django.db import migrations


BRACELET_METRIC_TYPES = [
    # (system_key, name_uz, unit, icon, value_format)
    ("heart_rate",      "Yurak urishi",         "bpm",      "❤️",  "number"),
    ("steps",           "Qadam",                "qadam",    "🚶",  "number"),
    ("spo2",            "Kislorod (SpO2)",      "%",        "🫁",  "number"),
    ("blood_pressure",  "Qon bosimi",           "mmHg",     "🔴",  "range"),
    ("temperature",     "Harorat",              "°C",       "🌡️",  "number"),
    ("calories_burned", "Yondirilgan kaloriya", "kcal",     "🔥",  "number"),
    ("distance_m",      "Masofa",               "m",        "📏",  "number"),
    ("hrv",             "HRV",                  "ms",       "💓",  "number"),
    ("weight",          "Vazn",                 "kg",       "⚖️",  "number"),
    ("sleep",           "Uyqu",                 "daq",      "😴",  "number"),
    ("glucose",         "Qondagi qand",         "mmol/L",   "🩸",  "number"),
    ("hba1c",           "HbA1c",                "%",        "🧪",  "number"),
    ("stress",          "Stress darajasi",      "",         "😰",  "number"),
    ("met",             "MET",                  "MET",      "🏃",  "number"),
]


def seed(apps, schema_editor):
    Type = apps.get_model("health_packages", "HealthIndicatorType")
    for key, name_uz, unit, icon, vf in BRACELET_METRIC_TYPES:
        Type.objects.get_or_create(
            system_key=key,
            defaults={
                "name": {"uz": name_uz, "ru": name_uz, "cyr": name_uz},
                "unit": unit,
                "icon": icon,
                "value_format": vf,
            },
        )


def unseed(apps, schema_editor):
    """Reverse — seed qilingan yozuvlarni o'chirmaymiz.

    HealthIndicator FK CASCADE bilan ulangan — type'ni o'chirsak bemor
    o'lchovlari ham yo'q bo'ladi. Migration'ni qaytarish kerak bo'lsa,
    avval yozuvlarni manual o'chiring.
    """
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("health_packages", "0012_alter_healthindicator_options_and_more"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
