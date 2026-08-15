from .common import *  # noqa: F401,F403 - header importlar + helperlar

class DoctorPayoutCard(models.Model):
    """Doctor saqlangan kartalari — bir nechta bo'lishi mumkin, bittasi primary."""

    class CardType(models.TextChoices):
        UZCARD = "uzcard", "Uzcard"
        HUMO = "humo", "Humo"
        VISA = "visa", "Visa"
        MASTERCARD = "mastercard", "Mastercard"
        OTHER = "other", "Boshqa"

    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="payout_cards",
    )
    card_type = models.CharField(
        max_length=15, choices=CardType.choices, default=CardType.OTHER
    )
    card_number = models.CharField(max_length=19, help_text="16 raqamli PAN")
    card_holder = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100, blank=True)
    expiry_month = models.PositiveSmallIntegerField(help_text="1..12")
    expiry_year = models.PositiveSmallIntegerField(help_text="2-xonali (masalan, 27)")
    is_primary = models.BooleanField(default=False)

    # ATMOS ASL (avtomatik payout) — karta /info orqali registratsiya qilingach to'ldiriladi
    atmos_asl_card_id = models.BigIntegerField(
        null=True, blank=True, db_index=True,
        help_text="ATMOS ASL tomondagi karta ID — /info chaqirilganda olinadi"
    )
    atmos_asl_phone = models.CharField(
        max_length=20, blank=True,
        help_text="ASL qaytargan karta-ga bog'langan telefon raqami"
    )
    atmos_asl_processing_type = models.CharField(
        max_length=20, blank=True,
        help_text="UZCARD / HUMO — ASL processing_type"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_primary", "-created_at"]
        indexes = [
            models.Index(fields=["doctor", "-is_primary"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "card_number"],
                name="unique_doctor_card_number",
            ),
        ]

    def __str__(self):
        return f"{self.doctor} — **** {self.card_number[-4:]}"

    @property
    def card_last4(self):
        return self.card_number[-4:] if self.card_number else ""

    @property
    def expiry_display(self):
        return f"{self.expiry_month:02d}/{self.expiry_year:02d}"

    def make_primary(self):
        """Atomic: shu kartani primary qiladi, qolganlarini False ga o'tkazadi."""
        with transaction.atomic():
            DoctorPayoutCard.objects.filter(doctor_id=self.doctor_id).exclude(
                pk=self.pk
            ).update(is_primary=False)
            DoctorPayoutCard.objects.filter(pk=self.pk).update(is_primary=True)
        self.is_primary = True

class PayoutRequest(models.Model):
    """Doctor pul yechish so'rovi (manual flow — admin qo'lda bank o'tkazma qiladi)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        COMPLETED = "completed", "Bajarilgan"
        REJECTED = "rejected", "Rad etilgan"
        CANCELLED = "cancelled", "Bekor qilingan"

    class SubStatus(models.TextChoices):
        """Pending ichidagi UI sub-state'lari (status=pending bo'lganda mazmunli)."""

        SUBMITTED = "submitted", "Yuborildi"
        IN_REVIEW = "in_review", "Tekshirilmoqda"
        ATMOS_PROCESSING = "atmos_processing", "ATMOS orqali ishlanmoqda"

    class Method(models.TextChoices):
        """Payout qaysi yo'l bilan bajariladi: manual (admin bank o'tkazma) yoki ATMOS ASL (avtomatik)."""

        MANUAL = "manual", "Qo'lda (admin bank o'tkazma qiladi)"
        ATMOS_ASL = "atmos_asl", "ATMOS ASL (avtomatik)"

    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="payout_requests",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Karta snapshot (so'rov yaratilgan paytdagi)
    card = models.ForeignKey(
        DoctorPayoutCard,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payouts",
        help_text="Snapshot manbasi; karta o'chirilsa NULL bo'ladi.",
    )
    card_type = models.CharField(
        max_length=15, choices=DoctorPayoutCard.CardType.choices, blank=True
    )
    card_number = models.CharField(max_length=19)
    card_holder = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100, blank=True)

    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    sub_status = models.CharField(
        max_length=20,
        choices=SubStatus.choices,
        default=SubStatus.SUBMITTED,
        help_text="Pending paytida UI uchun batafsil holat",
    )

    # Admin maydonlari
    admin_note = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)
    transaction_ref = models.CharField(
        max_length=255, blank=True, help_text="Bank tranzaksiya ID si (ixtiyoriy)"
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_payouts",
    )

    # Payout method — qaysi yo'l bilan bajarilgan (audit)
    method = models.CharField(
        max_length=15,
        choices=Method.choices,
        default=Method.MANUAL,
        help_text="MANUAL — admin bank o'tkazma · ATMOS_ASL — avtomatik API",
    )

    # ATMOS ASL audit trail (faqat method=atmos_asl bo'lganda to'ldiriladi)
    atmos_asl_ext_id = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="ASL ga jo'natilgan idempotency key (uuid4)"
    )
    atmos_asl_transaction_id = models.BigIntegerField(
        null=True, blank=True, db_index=True,
        help_text="ASL tomondagi transaction_id (/create javobidan)"
    )
    atmos_asl_state = models.SmallIntegerField(
        null=True, blank=True,
        help_text="Oxirgi ASL state: 2=ACCEPTED, 4=FINISHED, 5=FAILED, 13=PENDING"
    )
    atmos_asl_error = models.CharField(
        max_length=500, blank=True,
        help_text="state=5 bo'lganda billing_error_message; yoki API error description"
    )
    atmos_asl_poll_count = models.PositiveSmallIntegerField(
        default=0, help_text="Necha marta /id orqali pollangan (debug uchun)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.doctor} — {self.amount} so'm ({self.get_status_display()})"

    @property
    def card_last4(self):
        return self.card_number[-4:] if self.card_number else ""

    @property
    def detail_status(self):
        """Frontend uchun yagona status: submitted|in_review|paid|rejected|cancelled."""
        if self.status == self.Status.COMPLETED:
            return "paid"
        if self.status == self.Status.REJECTED:
            return "rejected"
        if self.status == self.Status.CANCELLED:
            return "cancelled"
        return self.sub_status  # pending → submitted yoki in_review

    @property
    def detail_status_label(self):
        return {
            "submitted": "Yuborildi",
            "in_review": "Tekshirilmoqda",
            "atmos_processing": "ATMOS orqali yuborilmoqda",
            "paid": "Kartaga tushdi",
            "rejected": "Rad etildi",
            "cancelled": "Bekor qilindi",
        }.get(self.detail_status, "")


# --- To'lovlar ---
