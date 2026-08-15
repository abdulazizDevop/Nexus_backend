"""Analiz katalogi i18n — AnalysisType/Indicator/Preparation JSONField'ga.

FAZA I1-I3 (audit i18n plan):
- AnalysisType.name, .description: CharField/TextField → JSONField
- AnalysisIndicator.name: CharField → JSONField
- AnalysisPreparation.title, .description: CharField → JSONField

Eski qiymat: oddiy string ("Glyukoza"). Yangi: JSON `{"uz": "Glyukoza"}`.

Pattern Specialty (doctors/0011) bilan bir xil:
1. CharField'da unique constraint olib tashlanmaydi (yo'q edi)
2. AlterModelOptions — ordering'dan name/title olib tashlash (JSON field
   string sort qila olmaydi)
3. RunPython: eski string → JSON-encoded string (hali CharField/TextField)
4. AlterField → JSONField

Postgres safe: atomic=False (DDL+DML).

Keyingi qadam: `python manage.py translate_existing` — 3 tilga to'ldirish.
"""

import json
from django.db import migrations, models


def encode_existing_to_json(apps, schema_editor):
    """Eski string qiymatlarni JSON-encoded string'ga aylantirish.

    CharField/TextField hali ham eski type, lekin qiymat endi valid JSON
    object: `'{"uz": "Glyukoza"}'`. Keyingi AlterField (JSONField) shu
    qiymatni ob'ekt sifatida tushunadi.
    """
    targets = [
        ("medical", "AnalysisType", ["name", "description"]),
        ("medical", "AnalysisIndicator", ["name"]),
        ("medical", "AnalysisPreparation", ["title", "description"]),
    ]

    for app_label, model_name, fields in targets:
        Model = apps.get_model(app_label, model_name)
        for obj in Model.objects.all():
            updated = False
            for field in fields:
                raw = getattr(obj, field, None) or ""
                text = raw.strip() if isinstance(raw, str) else ""
                # Allaqachon JSON-encoded bo'lishi ehtimoli
                if text.startswith("{") and text.endswith("}"):
                    try:
                        json.loads(text)
                        continue
                    except Exception:
                        pass
                new_value = json.dumps({"uz": text}, ensure_ascii=False) if text else json.dumps({})
                setattr(obj, field, new_value)
                updated = True
            if updated:
                obj.save(update_fields=fields)


def decode_json_to_string(apps, schema_editor):
    """Reverse — JSON dict'dan uz qiymatini olib oddiy string sifatida."""
    targets = [
        ("medical", "AnalysisType", ["name", "description"]),
        ("medical", "AnalysisIndicator", ["name"]),
        ("medical", "AnalysisPreparation", ["title", "description"]),
    ]
    for app_label, model_name, fields in targets:
        Model = apps.get_model(app_label, model_name)
        for obj in Model.objects.all():
            updated = False
            for field in fields:
                raw = getattr(obj, field, None)
                if isinstance(raw, dict):
                    value = raw.get("uz") or next(iter(raw.values()), "")
                    setattr(obj, field, value)
                    updated = True
            if updated:
                obj.save(update_fields=fields)


class Migration(migrations.Migration):
    # PostgreSQL'da DDL + DML aralashganda atomic transaction muammo qiladi
    # ('pending trigger events'). atomic=False har step alohida.
    atomic = False

    dependencies = [
        ("medical", "0008_remove_analysis_is_private_alter_analysis_recipients_and_more"),
    ]

    operations = [
        # 1) ordering'dan name/title olib tashlash — JSON field string sort
        #    qila olmaydi (DB level)
        migrations.AlterModelOptions(
            name="analysistype",
            options={"ordering": ["order"]},
        ),
        migrations.AlterModelOptions(
            name="analysisindicator",
            options={"ordering": ["order"]},
        ),
        migrations.AlterModelOptions(
            name="analysispreparation",
            options={"ordering": ["order"]},
        ),
        # 2) Data: eski string → JSON-encoded string (CharField/TextField ichida)
        migrations.RunPython(encode_existing_to_json, decode_json_to_string),
        # 3) CharField/TextField → JSONField (default dict). Eski qiymatlar
        #    endi valid JSON object.
        migrations.AlterField(
            model_name="analysistype",
            name="name",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="analysistype",
            name="description",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="analysisindicator",
            name="name",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="analysispreparation",
            name="title",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="analysispreparation",
            name="description",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
