from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_patient_profile  # underscore helper (star bermaydi)
from .tariff import DoctorTariff, DoctorTariffPurchase

class OfflinePayment(models.Model):
    """Bemor doctor tarifini NAQD/offline to'lagani — doctor tasdiqlashi kerak.

    Bemor "offline to'ladim" deydi → doctorga tasdiqlash uchun boradi. Doctor
    tasdiqlasa, platforma komissiyasi doctor balansidan yechiladi (doctor naqdni
    o'zi olgani uchun earnings balansga QO'SHILMAYDI) va bemorga tarif access
    beriladi (DoctorTariffPurchase, source=offline).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Tasdiqlash kutilmoqda"
        CONFIRMED = "confirmed", "Tasdiqlangan"
        REJECTED = "rejected", "Rad etilgan"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="offline_payments",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="offline_payments",
        null=True,
        blank=True,
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="offline_payments",
    )
    tariff = models.ForeignKey(
        DoctorTariff,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offline_payments",
    )
    tariff_snapshot = models.JSONField(
        default=dict, help_text="Tarif ma'lumotlari so'rov paytidagi nusxasi"
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="So'rov paytida kelishilgan narx (snapshot).",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )

    # Tasdiqlashda to'ldiriladi (snapshot)
    commission_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    commission_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    purchase = models.OneToOneField(
        DoctorTariffPurchase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="offline_payment",
        help_text="Tasdiqlanganda yaratilgan tarif xaridi.",
    )
    rejection_reason = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_offline_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(
        null=True, blank=True, help_text="Tasdiqlangan/rad etilgan vaqt."
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["patient", "status"]),
        ]
        constraints = [
            # Bitta (patient, doctor) uchun bir vaqtda faqat bitta PENDING —
            # doctor bir nechtasini confirm qilib komissiyani ikki marta
            # yechishining oldini oladi.
            models.UniqueConstraint(
                fields=["patient", "doctor"],
                condition=models.Q(status="pending"),
                name="unique_pending_offline_payment",
            ),
        ]

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "patient")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient} → {self.doctor} ({self.amount} so'm, {self.get_status_display()})"


# --- Doctor payout (pul yechish) ---
