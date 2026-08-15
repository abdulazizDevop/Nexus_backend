# Generated for doctor payout hold feature (2-day hold).

from datetime import timedelta

from django.db import migrations, models


def backfill_available_at(apps, schema_editor):
    """Mavjud purchase'larga available_at = created_at + 2 kun qo'shamiz.

    Eski purchase'lar uchun hold tugagan bo'ladi (created_at yetarli o'tib ketgan).
    """
    DoctorTariffPurchase = apps.get_model("payments", "DoctorTariffPurchase")
    for p in DoctorTariffPurchase.objects.filter(available_at__isnull=True).iterator():
        p.available_at = p.created_at + timedelta(days=2)
        p.save(update_fields=["available_at"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0012_doctorpayoutcard_atmos_asl_card_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='doctortariffpurchase',
            name='available_at',
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Doctor balansidagi shu summa qaysi vaqtdan payout uchun ochiq (hold tugagach)",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name='doctortariffpurchase',
            index=models.Index(fields=['doctor', 'available_at'], name='payments_do_doctor__7483ee_idx'),
        ),
        migrations.RunPython(backfill_available_at, noop_reverse),
    ]
