"""Diet AI patient_profile backfill (Conversation, Restriction, Entry, Usage)."""

from django.db import migrations


def backfill(apps, schema_editor):
    DietConversation = apps.get_model("diet_ai", "DietConversation")
    DietRestriction = apps.get_model("diet_ai", "DietRestriction")
    DietEntry = apps.get_model("diet_ai", "DietEntry")
    DietDailyUsage = apps.get_model("diet_ai", "DietDailyUsage")
    Patient = apps.get_model("users", "Patient")

    counts = {"conv": 0, "restr": 0, "entry": 0, "usage": 0}

    for c in DietConversation.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=c.user_id)
        c.patient_profile_id = pp.id
        c.save(update_fields=["patient_profile"])
        counts["conv"] += 1

    for r in DietRestriction.objects.filter(patient_profile__isnull=True).only(
        "id", "patient_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=r.patient_id)
        r.patient_profile_id = pp.id
        r.save(update_fields=["patient_profile"])
        counts["restr"] += 1

    for e in DietEntry.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=e.user_id)
        e.patient_profile_id = pp.id
        e.save(update_fields=["patient_profile"])
        counts["entry"] += 1

    for u in DietDailyUsage.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=u.user_id)
        u.patient_profile_id = pp.id
        u.save(update_fields=["patient_profile"])
        counts["usage"] += 1

    print(
        f"  → DietConversation: {counts['conv']}, Restriction: {counts['restr']}, "
        f"Entry: {counts['entry']}, Usage: {counts['usage']}"
    )


def reverse_backfill(apps, schema_editor):
    for model_name in ("DietConversation", "DietRestriction", "DietEntry", "DietDailyUsage"):
        apps.get_model("diet_ai", model_name).objects.update(patient_profile=None)


class Migration(migrations.Migration):
    dependencies = [
        ("diet_ai", "0004_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
