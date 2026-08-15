"""Specialty.name: CharField → JSONField (i18n bilan).

Eski qiymat: oddiy string ("Kardiolog"). Yangi: JSON `{"uz": "Kardiolog"}`.

Bu migratsiya 3 bosqichli:
1. Eski string'larni JSON-encoded string'ga aylantirish (hali CharField'da)
2. CharField'da unique constraint olib tashlanadi (JSON dict'ni Postgres
   to'g'ridan-to'g'ri unique qila olmaydi, kerak bo'lsa keyinroq expression
   index qilamiz)
3. CharField → JSONField (default dict)

Keyingi migration (0012 yo'q — bitta migration'da yetadi) tarjimani Gemini
orqali to'ldiradi: `python manage.py translate_specialties` command.
"""

import json
from django.db import migrations, models


def encode_existing_to_json(apps, schema_editor):
    """Eski string qiymatlarni JSON-encoded string'ga aylantirish.

    CharField hali ham CharField, lekin `name` ichidagi qiymat endi
    valid JSON object: `'{"uz": "Kardiolog"}'`. Keyingi AlterField
    JSON CHECK constraint'iga muvofiq keladi.
    """
    Specialty = apps.get_model("doctors", "Specialty")
    for obj in Specialty.objects.all():
        raw = obj.name or ""
        text = raw.strip() if isinstance(raw, str) else ""
        # Allaqachon JSON-encoded bo'lishi ehtimoli
        if text.startswith("{") and text.endswith("}"):
            try:
                json.loads(text)
                continue  # OK, valid JSON object
            except Exception:
                pass
        # Oddiy string — uz tiliga aylantiramiz
        obj.name = json.dumps({"uz": text}, ensure_ascii=False)
        obj.save(update_fields=["name"])


def decode_json_to_string(apps, schema_editor):
    """Reverse — JSON'dan uz qiymatini olib oddiy string sifatida saqlash."""
    Specialty = apps.get_model("doctors", "Specialty")
    for obj in Specialty.objects.all():
        raw = obj.name
        if isinstance(raw, dict):
            obj.name = raw.get("uz") or next(iter(raw.values()), "")
            obj.save(update_fields=["name"])


class Migration(migrations.Migration):
    # PostgreSQL'da DDL + DML aralashganda atomic transaction muammo qiladi
    # (`pending trigger events`). `atomic = False` har step alohida.
    atomic = False

    dependencies = [
        ("doctors", "0010_backfill_doctorpatient_patient_profile"),
    ]

    operations = [
        # 1) Avval CharField'da unique'ni olib tashlash (JSON object unique-able emas
        #    standartda — kerak bo'lsa keyinroq Postgres expression index qilamiz)
        migrations.AlterField(
            model_name="specialty",
            name="name",
            field=models.CharField(max_length=255),
        ),
        # 2) Data: eski string → JSON-encoded string (CharField ichida)
        migrations.RunPython(encode_existing_to_json, decode_json_to_string),
        # 3) Meta options'ni yangilash (ordering olib tashlandi, JSON field
        #    Lower("name") bilan tartiblanmaydi)
        migrations.AlterModelOptions(
            name="specialty",
            options={"verbose_name_plural": "specialties"},
        ),
        # 4) CharField → JSONField. Eski qiymatlar endi valid JSON object,
        #    SQLite va Postgres CHECK constraint bilan mos.
        migrations.AlterField(
            model_name="specialty",
            name="name",
            field=models.JSONField(default=dict),
        ),
    ]
