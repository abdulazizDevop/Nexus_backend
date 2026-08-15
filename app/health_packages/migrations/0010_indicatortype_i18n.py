"""HealthIndicatorType.name: CharField → JSONField (i18n).

Specialty bilan bir xil 4-bosqichli xavfsiz migratsiya:
1. CharField'da unique olib tashlanadi
2. RunPython: eski string → JSON-encoded string `{"uz": "Vazn"}`
3. AlterField CharField → JSONField (eski qiymatlar endi valid JSON)
"""

import json
from django.db import migrations, models


def encode_to_json(apps, schema_editor):
    Model = apps.get_model("health_packages", "HealthIndicatorType")
    for obj in Model.objects.all():
        raw = obj.name or ""
        text = raw.strip() if isinstance(raw, str) else ""
        if text.startswith("{") and text.endswith("}"):
            try:
                json.loads(text)
                continue
            except Exception:
                pass
        obj.name = json.dumps({"uz": text}, ensure_ascii=False)
        obj.save(update_fields=["name"])


def decode_to_string(apps, schema_editor):
    Model = apps.get_model("health_packages", "HealthIndicatorType")
    for obj in Model.objects.all():
        raw = obj.name
        if isinstance(raw, dict):
            obj.name = raw.get("uz") or next(iter(raw.values()), "")
            obj.save(update_fields=["name"])


class Migration(migrations.Migration):
    # PostgreSQL'da DDL + DML aralashganda atomic transaction muammo qiladi
    # (`pending trigger events`). `atomic = False` har step alohida.
    atomic = False

    dependencies = [
        ("health_packages", "0009_backfill_patient_profile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="healthindicatortype",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(encode_to_json, decode_to_string),
        migrations.AlterField(
            model_name="healthindicatortype",
            name="name",
            field=models.JSONField(default=dict),
        ),
    ]
