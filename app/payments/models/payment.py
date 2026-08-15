from .common import *  # noqa: F401,F403 - header importlar + helperlar

class Payment(models.Model):
    """Umumiy to'lov yozuvi (Pro ham, DoctorTariff ham)"""

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        COMPLETED = "completed", "Yakunlangan"
        FAILED = "failed", "Xatolik"
        CANCELLED = "cancelled", "Bekor qilingan"

    class Provider(models.TextChoices):
        PAYME = "payme", "Payme"
        CLICK = "click", "Click"
        ATMOS = "atmos", "Atmos"
        # Dev/test: tashqi gateway'siz yakunlangan to'lov (onlayn to'lovni
        # taqlid qiladi). Faqat MANUAL_PAYMENT_ENABLED=True bo'lganda.
        MANUAL = "manual", "Qo'lda (test)"
        # HAQIQIY naqd sotuv: pul klinika kassasida qoladi, platformaga
        # komissiya QARZ bo'ladi (balansdan ayriladi).
        CASH = "cash", "Naqd (kassa)"

    class Purpose(models.TextChoices):
        PRO_SUBSCRIPTION = "pro_subscription", "Pro obuna"
        DOCTOR_TARIFF = "doctor_tariff", "Doctor tarifi"
        BALANCE_TOPUP = "balance_topup", "Balans to'ldirish"
        CONSULTATION = "consultation", "Konsultatsiya"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    provider = models.CharField(max_length=20, choices=Provider.choices)
    provider_transaction_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    # Paycom kabinetidagi "Реквизиты платёжа" → "Название Реквизита" sozlamasi
    # `balance_id` qilib o'rnatilgan (kabinet edit qilib bo'lmaydi — security).
    # paytechuz `Payment.objects.get(balance_id=...)` qiladi (ACCOUNT_FIELD), shuning uchun
    # ustun fizik kerak. Qiymat — `id` bilan bir xil (save() da auto-fill bo'ladi).
    balance_id = models.PositiveBigIntegerField(
        unique=True, null=True, blank=True, db_index=True
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["purpose", "status"]),
        ]

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and self.balance_id is None:
            Payment.objects.filter(pk=self.pk).update(balance_id=self.pk)
            self.balance_id = self.pk

    def __str__(self):
        return f"{self.user} — {self.amount} ({self.get_provider_display()}, {self.get_status_display()})"

class AtmosSavedCard(models.Model):
    """Patient saqlangan kartasi (Atmos card_token) — to'lov tezligini oshirish uchun.

    Atmos `bind-card/confirm` muvaffaqiyatli bo'lganda token, masked PAN va
    expiry saqlanadi. Token plain matnda saqlanadi (foydalanuvchi tanlovi).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="atmos_cards",
    )
    atmos_card_id = models.BigIntegerField(
        unique=True, help_text="Atmos tomondagi card_id"
    )
    card_token = models.TextField(help_text="Atmos card_token — remove_card uchun")
    card_number = models.CharField(
        max_length=16, blank=True, help_text="To'liq PAN — pre-apply uchun"
    )
    pan_masked = models.CharField(max_length=20, help_text="986009******1840")
    expiry = models.CharField(max_length=4, help_text="YYMM, masalan 2505")
    card_holder = models.CharField(max_length=100, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "-created_at"]
        indexes = [
            models.Index(fields=["user", "-is_primary"]),
        ]

    def __str__(self):
        return f"{self.user} — {self.pan_masked}"

    @property
    def pan_last4(self):
        return self.pan_masked[-4:] if self.pan_masked else ""

    def make_primary(self):
        with transaction.atomic():
            AtmosSavedCard.objects.filter(user_id=self.user_id).exclude(
                pk=self.pk
            ).update(is_primary=False)
            AtmosSavedCard.objects.filter(pk=self.pk).update(is_primary=True)
        self.is_primary = True
