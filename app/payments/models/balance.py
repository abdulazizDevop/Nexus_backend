from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .tariff import DoctorTariffPurchase

class DoctorBalance(models.Model):
    """Doctor ichki hisobi — tariflardan tushgan pul"""

    doctor = models.OneToOneField(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="balance",
    )
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total_earned = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0")
    )
    total_withdrawn = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0")
    )
    total_commission_paid = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0"),
        help_text="Offline to'lovlar uchun balansdan yechilgan platforma komissiyasi (jami).",
    )
    total_topped_up = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0"),
        help_text="Doctor o'zi to'ldirgan summa (jami) — earnings emas.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.doctor} — {self.balance} so'm"

    def add_earnings(self, amount):
        """Atomic F() increment — race conditionsiz (tarif sotuvidan tushgan pul)."""
        with transaction.atomic():
            DoctorBalance.objects.filter(pk=self.pk).update(
                balance=F("balance") + amount,
                total_earned=F("total_earned") + amount,
            )
        self.refresh_from_db()

    def confirm_withdrawal(self, amount):
        """Admin payout ni complete qilganda — balans kamayadi, total_withdrawn ko'tariladi."""
        with transaction.atomic():
            DoctorBalance.objects.filter(pk=self.pk).update(
                balance=F("balance") - amount,
                total_withdrawn=F("total_withdrawn") + amount,
            )
        self.refresh_from_db()

    def charge_commission(self, amount):
        """Offline to'lov tasdiqlanganda — platforma komissiyasi balansdan yechiladi.

        Payout emas (total_withdrawn'ga tegmaydi) — bu platforma charge'i.
        Manfiyga ketmasligi chaqiruvchi (confirm view) tomonidan
        select_for_update + balance tekshiruvi bilan kafolatlanadi.
        """
        with transaction.atomic():
            DoctorBalance.objects.filter(pk=self.pk).update(
                balance=F("balance") - amount,
                total_commission_paid=F("total_commission_paid") + amount,
            )
        self.refresh_from_db()

    def add_topup(self, amount):
        """Doctor o'z balansini to'ldiradi — faqat balance oshadi (total_earned EMAS)."""
        with transaction.atomic():
            DoctorBalance.objects.filter(pk=self.pk).update(
                balance=F("balance") + amount,
                total_topped_up=F("total_topped_up") + amount,
            )
        self.refresh_from_db()

    @property
    def held_amount(self):
        """Hold davrida muzlatilgan summa (hali payout uchun ochiq emas)."""
        from django.db.models import Sum
        now = timezone.now()
        agg = DoctorTariffPurchase.objects.filter(
            doctor_id=self.doctor_id,
            available_at__gt=now,
        ).aggregate(total=Sum("doctor_earnings"))
        return agg["total"] or Decimal("0")

    @property
    def available_balance(self):
        """Payout uchun ochiq summa = balance - held_amount.

        Manfiy chiqmaydi (eski purchase'lar `available_at=NULL` bo'lsa hold yo'q).
        """
        result = self.balance - self.held_amount
        return result if result > 0 else Decimal("0")

class BalanceTopup(models.Model):
    """Doctor o'z balansini to'ldirgani — provayder webhook'i yakunlanganda yaratiladi.

    Idempotency: `payment` OneToOne — bitta Payment uchun bitta topup yozuvi.
    To'liq summa balansga qo'shiladi (komissiyasiz — doctor o'z puli).
    """

    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="balance_topups",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment = models.OneToOneField(
        "Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="balance_topup",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.doctor} +{self.amount} so'm (topup)"


# --- Atmos (karta gateway) ---
