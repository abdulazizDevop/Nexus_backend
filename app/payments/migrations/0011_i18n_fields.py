"""Pro/Tariff modellarining matnli maydonlarini i18n JSON ga ko'chirish.

Modellar va maydonlar:
- ProPlan.name             CharField  → JSONField
- ProFeatureFlag.label     CharField  → JSONField
- ProFeatureFlag.description TextField → JSONField
- DoctorTariff.name        CharField  → JSONField
- DoctorTariff.description TextField  → JSONField
- DoctorTariff.discount_label CharField → JSONField
- DoctorTariff.features    JSONField (list) → JSONField (dict per lang)

Specialty pattern'i bilan bir xil 3-bosqichli (CharField/TextField ichida
JSON-encode, keyin AlterField). Features esa list → dict alohida ko'chiriladi.
"""

import json
from django.db import migrations, models


# --- Oddiy text field'lar uchun helper ---

def _encode_text(apps, model_name, field_name, source_lang="uz"):
    """Apps registry'dan model olib, har yozuvda field'ni JSON encode qiladi."""
    Model = apps.get_model("payments", model_name)
    for obj in Model.objects.all():
        raw = getattr(obj, field_name) or ""
        text = raw.strip() if isinstance(raw, str) else ""
        if text.startswith("{") and text.endswith("}"):
            try:
                json.loads(text)
                continue
            except Exception:
                pass
        setattr(
            obj,
            field_name,
            json.dumps({source_lang: text}, ensure_ascii=False),
        )
        obj.save(update_fields=[field_name])


def _decode_text(apps, model_name, field_name):
    """JSON dict'dan uz qiymatini olib oddiy string sifatida saqlash."""
    Model = apps.get_model("payments", model_name)
    for obj in Model.objects.all():
        raw = getattr(obj, field_name)
        if isinstance(raw, dict):
            setattr(obj, field_name, raw.get("uz") or next(iter(raw.values()), ""))
            obj.save(update_fields=[field_name])


# --- ProPlan ---

def encode_proplan_name(apps, _):
    _encode_text(apps, "ProPlan", "name")


def decode_proplan_name(apps, _):
    _decode_text(apps, "ProPlan", "name")


# --- ProFeatureFlag ---

def encode_profeature_text(apps, _):
    _encode_text(apps, "ProFeatureFlag", "label")
    _encode_text(apps, "ProFeatureFlag", "description")


def decode_profeature_text(apps, _):
    _decode_text(apps, "ProFeatureFlag", "label")
    _decode_text(apps, "ProFeatureFlag", "description")


# --- DoctorTariff ---

def encode_tariff_text(apps, _):
    _encode_text(apps, "DoctorTariff", "name")
    _encode_text(apps, "DoctorTariff", "description")
    _encode_text(apps, "DoctorTariff", "discount_label")


def decode_tariff_text(apps, _):
    _decode_text(apps, "DoctorTariff", "name")
    _decode_text(apps, "DoctorTariff", "description")
    _decode_text(apps, "DoctorTariff", "discount_label")


# --- DoctorTariff.features: list → dict per lang ---

def features_list_to_dict(apps, _):
    """`features` allaqachon JSONField, lekin list edi. Endi dict per lang.

    [old]: ["Cheklanmagan chat", "24/7 maslahat"]
    [new]: {"uz": ["Cheklanmagan chat", "24/7 maslahat"], "ru": [], "cyr": []}

    Tarjima Gemini orqali keyin `translate_existing` command'da to'ldiriladi.
    """
    Tariff = apps.get_model("payments", "DoctorTariff")
    for obj in Tariff.objects.all():
        raw = obj.features
        if isinstance(raw, list):
            obj.features = {"uz": [str(x) for x in raw if x], "ru": [], "cyr": []}
            obj.save(update_fields=["features"])
        elif raw is None:
            obj.features = {"uz": [], "ru": [], "cyr": []}
            obj.save(update_fields=["features"])
        # Allaqachon dict bo'lsa — tegmaymiz


def features_dict_to_list(apps, _):
    Tariff = apps.get_model("payments", "DoctorTariff")
    for obj in Tariff.objects.all():
        raw = obj.features
        if isinstance(raw, dict):
            obj.features = list(raw.get("uz") or next(iter(raw.values()), []) or [])
            obj.save(update_fields=["features"])


class Migration(migrations.Migration):
    # PostgreSQL'da bitta atomic transactionda DDL (AlterField) va DML (RunPython)
    # aralashganda `pending trigger events` xatosi chiqadi (har AlterField'dan
    # keyin Postgres trigger event saqlaydi). `atomic = False` har step'ni
    # alohida transactionda bajaradi — SQLite va Postgres ikkalasida ham xavfsiz.
    atomic = False

    dependencies = [
        ("payments", "0010_alter_payment_provider_atmossavedcard"),
    ]

    operations = [
        # === ProPlan.name ===
        migrations.AlterField(
            model_name="proplan",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(encode_proplan_name, decode_proplan_name),
        migrations.AlterField(
            model_name="proplan",
            name="name",
            field=models.JSONField(default=dict),
        ),
        # === ProFeatureFlag.label + description ===
        migrations.AlterField(
            model_name="profeatureflag",
            name="label",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="profeatureflag",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.RunPython(encode_profeature_text, decode_profeature_text),
        migrations.AlterField(
            model_name="profeatureflag",
            name="label",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="profeatureflag",
            name="description",
            field=models.JSONField(blank=True, default=dict),
        ),
        # === DoctorTariff.name + description + discount_label ===
        migrations.AlterField(
            model_name="doctortariff",
            name="name",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterField(
            model_name="doctortariff",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="doctortariff",
            name="discount_label",
            field=models.CharField(max_length=100, blank=True),
        ),
        migrations.RunPython(encode_tariff_text, decode_tariff_text),
        migrations.AlterField(
            model_name="doctortariff",
            name="name",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="doctortariff",
            name="description",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="doctortariff",
            name="discount_label",
            field=models.JSONField(blank=True, default=dict),
        ),
        # === DoctorTariff.features: list → dict ===
        migrations.RunPython(features_list_to_dict, features_dict_to_list),
        migrations.AlterField(
            model_name="doctortariff",
            name="features",
            field=models.JSONField(
                default=dict,
                help_text='Til boyicha massivlar: {"uz": [...], "ru": [...], "cyr": [...]}',
            ),
        ),
    ]
