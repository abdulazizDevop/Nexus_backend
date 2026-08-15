"""DoctorPayoutCard (multi-card) + PayoutRequest.sub_status va FK card.

Bosqichlar:
  1) DoctorPayoutCard yaratiladi.
  2) PayoutRequest'ga `sub_status`, `card`, `card_type` qo'shiladi.
     - mavjud `pending` so'rovlar `sub_status='submitted'` bilan ketadi (default).
  3) Eski DoctorPayoutMethod'dagi har bir doctor karta DoctorPayoutCard'ga
     primary qilib ko'chiriladi (expiry'siz — eski modelda yo'q, default 12/30).
  4) DoctorPayoutMethod o'chiriladi.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_cards(apps, schema_editor):
    DoctorPayoutMethod = apps.get_model("payments", "DoctorPayoutMethod")
    DoctorPayoutCard = apps.get_model("payments", "DoctorPayoutCard")
    PayoutRequest = apps.get_model("payments", "PayoutRequest")

    for method in DoctorPayoutMethod.objects.all():
        # Idempotent: agar shu doctor + card_number bo'lsa, skip
        card, _ = DoctorPayoutCard.objects.get_or_create(
            doctor_id=method.doctor_id,
            card_number=method.card_number,
            defaults={
                "card_type": "other",
                "card_holder": method.card_holder,
                "bank_name": method.bank_name or "",
                # Eski modelda expiry yo'q — placeholder. Doctor keyin yangilaydi.
                "expiry_month": 12,
                "expiry_year": 30,
                "is_primary": True,
            },
        )
        # Mavjud PayoutRequest'larga card snapshot bog'lash (faqat shu doctorning
        # shu raqamga to'g'ri keladiganlari)
        PayoutRequest.objects.filter(
            doctor_id=method.doctor_id,
            card_number=method.card_number,
            card__isnull=True,
        ).update(card_id=card.id, card_type="other")


def reverse_noop(apps, schema_editor):
    """Backward migratsiya — yangi modellardagi ma'lumotni yo'qotmaslik uchun
    no-op. Roll-back kerak bo'lsa qo'lda."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0008_doctorpayoutmethod_payoutrequest"),
        ("doctors", "0010_backfill_doctorpatient_patient_profile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1) Yangi model
        migrations.CreateModel(
            name="DoctorPayoutCard",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "card_type",
                    models.CharField(
                        choices=[
                            ("uzcard", "Uzcard"),
                            ("humo", "Humo"),
                            ("visa", "Visa"),
                            ("mastercard", "Mastercard"),
                            ("other", "Boshqa"),
                        ],
                        default="other",
                        max_length=15,
                    ),
                ),
                ("card_number", models.CharField(help_text="16 raqamli PAN", max_length=19)),
                ("card_holder", models.CharField(max_length=100)),
                ("bank_name", models.CharField(blank=True, max_length=100)),
                ("expiry_month", models.PositiveSmallIntegerField(help_text="1..12")),
                (
                    "expiry_year",
                    models.PositiveSmallIntegerField(
                        help_text="2-xonali (masalan, 27)"
                    ),
                ),
                ("is_primary", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "doctor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payout_cards",
                        to="doctors.doctorprofile",
                    ),
                ),
            ],
            options={
                "ordering": ["-is_primary", "-created_at"],
                "indexes": [
                    models.Index(
                        fields=["doctor", "-is_primary"],
                        name="payments_do_doctor__836f2e_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("doctor", "card_number"),
                        name="unique_doctor_card_number",
                    )
                ],
            },
        ),
        # 2) PayoutRequest yangi maydonlar
        migrations.AddField(
            model_name="payoutrequest",
            name="sub_status",
            field=models.CharField(
                choices=[
                    ("submitted", "Yuborildi"),
                    ("in_review", "Tekshirilmoqda"),
                ],
                default="submitted",
                help_text="Pending paytida UI uchun batafsil holat",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="payoutrequest",
            name="card_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("uzcard", "Uzcard"),
                    ("humo", "Humo"),
                    ("visa", "Visa"),
                    ("mastercard", "Mastercard"),
                    ("other", "Boshqa"),
                ],
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name="payoutrequest",
            name="card",
            field=models.ForeignKey(
                blank=True,
                help_text="Snapshot manbasi; karta o'chirilsa NULL bo'ladi.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payouts",
                to="payments.doctorpayoutcard",
            ),
        ),
        # 3) Backfill
        migrations.RunPython(backfill_cards, reverse_noop),
        # 4) Eski modelni o'chirish
        migrations.DeleteModel(name="DoctorPayoutMethod"),
    ]
