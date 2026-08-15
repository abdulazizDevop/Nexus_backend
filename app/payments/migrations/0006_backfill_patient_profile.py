"""Payments patient_profile backfill (ProSubscription, DoctorTariffPurchase)."""

from django.db import migrations


def backfill(apps, schema_editor):
    ProSubscription = apps.get_model("payments", "ProSubscription")
    DoctorTariffPurchase = apps.get_model("payments", "DoctorTariffPurchase")
    Patient = apps.get_model("users", "Patient")

    sub_filled = 0
    for s in ProSubscription.objects.filter(patient_profile__isnull=True).only(
        "id", "user_id"
    ):
        pp, _ = Patient.objects.get_or_create(user_id=s.user_id)
        s.patient_profile_id = pp.id
        s.save(update_fields=["patient_profile"])
        sub_filled += 1

    purchase_filled = 0
    for p in DoctorTariffPurchase.objects.filter(
        patient_profile__isnull=True
    ).only("id", "patient_id"):
        pp, _ = Patient.objects.get_or_create(user_id=p.patient_id)
        p.patient_profile_id = pp.id
        p.save(update_fields=["patient_profile"])
        purchase_filled += 1

    print(
        f"  → ProSubscription: {sub_filled}, "
        f"DoctorTariffPurchase: {purchase_filled}"
    )


def reverse_backfill(apps, schema_editor):
    apps.get_model("payments", "ProSubscription").objects.update(patient_profile=None)
    apps.get_model("payments", "DoctorTariffPurchase").objects.update(
        patient_profile=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0005_add_patient_profile"),
        ("users", "0008_backfill_patient_profiles"),
    ]
    operations = [migrations.RunPython(backfill, reverse_backfill)]
