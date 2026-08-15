from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_patient_profile  # underscore helper (star bermaydi)

class DoctorTariff(models.Model):
    """Doctor o'zi yaratgan nazorat/konsultatsiya paketlari"""

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        APPROVED = "approved", "Tasdiqlangan"
        REJECTED = "rejected", "Rad etilgan"

    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Foiz"
        AMOUNT = "amount", "So'mda"

    class DiscountTarget(models.TextChoices):
        ALL = "all", "Hamma"
        NEW_PATIENTS = "new_patients", "Yangi bemorlar"

    # Moderatsiyaga ta'sir qiladigan maydonlar (o'zgarganda status → pending)
    MODERATED_FIELDS = ["name", "description", "price", "duration_days", "features"]

    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="tariffs",
    )
    # `name` 3 tilli JSON: `{"uz": "...", "ru": "...", "cyr": "..."}`
    name = models.JSONField(default=dict)
    # `description` 3 tilli JSON
    description = models.JSONField(default=dict, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    duration_days = models.PositiveIntegerField(help_text="Doctor belgilaydi")
    # `features` — top-level array per language:
    # `{"uz": ["Cheklanmagan chat"], "ru": ["Безлимитный чат"], "cyr": ["Чекланмаган чат"]}`
    features = models.JSONField(
        default=dict,
        help_text='Til boyicha massivlar: {"uz": [...], "ru": [...], "cyr": [...]}',
    )

    # Chegirma (moderatsiya talab qilmaydi)
    discount_enabled = models.BooleanField(default=False)
    discount_type = models.CharField(
        max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    discount_value = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    discount_target = models.CharField(
        max_length=15, choices=DiscountTarget.choices, default=DiscountTarget.ALL
    )
    discount_expires_at = models.DateField(null=True, blank=True)
    # `discount_label` 3 tilli JSON (masalan, "Yangi yil 30%" / "Новый год 30%")
    discount_label = models.JSONField(default=dict, blank=True)

    # Moderatsiya
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    rejection_reason = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False, help_text="'Mashhur' badge")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["status", "is_active"]),
        ]

    def __str__(self):
        return f"{self.doctor} — {pick_translation(self.name, 'uz')}"

    def _is_discount_active(self):
        if not self.discount_enabled or self.discount_value <= 0:
            return False
        if (
            self.discount_expires_at
            and self.discount_expires_at < timezone.now().date()
        ):
            return False
        return True

    @property
    def final_price(self):
        """Hamma uchun ko'rsatiladigan asosiy yakuniy narx (new_patients e'tiborsiz)."""
        if not self._is_discount_active():
            return self.price
        return self._calculate_discounted_price()

    def _calculate_discounted_price(self):
        if self.discount_type == self.DiscountType.PERCENT:
            discount = self.price * self.discount_value / Decimal("100")
        else:
            discount = self.discount_value
        result = self.price - discount
        return max(result, Decimal("0"))

    def get_price_for(self, patient):
        """Patient uchun haqiqiy narx — new_patients chegirmasini hisobga oladi."""
        if not self._is_discount_active():
            return self.price

        if self.discount_target == self.DiscountTarget.NEW_PATIENTS:
            has_previous = DoctorTariffPurchase.objects.filter(
                patient=patient, doctor=self.doctor
            ).exists()
            if has_previous:
                return self.price

        return self._calculate_discounted_price()

    def save(self, *args, **kwargs):
        """Moderatsiya maydonlari o'zgarsa status → pending"""
        if self.pk:
            old = DoctorTariff.objects.filter(pk=self.pk).first()
            if old and old.status == self.Status.APPROVED:
                changed = any(
                    getattr(old, f) != getattr(self, f) for f in self.MODERATED_FIELDS
                )
                if changed:
                    self.status = self.Status.PENDING
                    self.rejection_reason = ""
        super().save(*args, **kwargs)

class DoctorTariffPurchase(models.Model):
    """Patient sotib olgan doctor tarifi"""

    class Source(models.TextChoices):
        ONLINE = "online", "Online to'lov"
        OFFLINE = "offline", "Offline (naqd) — doctor tasdiqlagan"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tariff_purchases",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="tariff_purchases",
        null=True,
        blank=True,
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="tariff_sales",
    )
    tariff = models.ForeignKey(
        DoctorTariff, on_delete=models.SET_NULL, null=True, related_name="purchases"
    )
    tariff_snapshot = models.JSONField(
        default=dict, help_text="Tarif ma'lumotlari sotib olingan paytdagi nusxasi"
    )
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()

    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    doctor_earnings = models.DecimalField(max_digits=12, decimal_places=2)

    payment = models.OneToOneField(
        "Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tariff_purchase",
    )
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.ONLINE,
        help_text="Online to'lov yoki offline (naqd, doctor tasdiqlagan).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Doctor balansidagi shu summa qaysi vaqtdan payout uchun ochiq (hold tugagach)",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "expires_at"]),
            models.Index(fields=["doctor", "created_at"]),
            models.Index(fields=["doctor", "available_at"]),
        ]

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "patient")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient} → {self.doctor} ({self.amount_paid} so'm)"

    @property
    def is_active(self):
        return self.expires_at > timezone.now()

    @property
    def is_held(self):
        return bool(self.available_at and self.available_at > timezone.now())
