from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_patient_profile  # underscore helper (star bermaydi)

class ProPlan(models.Model):
    """Pro obunaning davomiylik variantlari (admin dinamik yaratadi).

    `name` 3 tilli JSON.
    """

    name = models.JSONField(default=dict)
    duration_days = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.PositiveSmallIntegerField(
        default=0, help_text="UI da ko'rsatish uchun"
    )
    is_popular = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "duration_days"]

    def __str__(self):
        return f"{pick_translation(self.name, 'uz')} ({self.duration_days} kun — {self.price} so'm)"

class ProFeatureFlag(models.Model):
    """Pro imkoniyatlar ro'yxati — admin paneldan boshqariladi.

    `label` va `description` 3 tilli JSON. `key` (slug) — internal kalit,
    tilga bog'liq emas.
    """

    key = models.SlugField(max_length=100, unique=True)
    label = models.JSONField(default=dict)
    icon = models.CharField(max_length=20, blank=True)
    description = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "key"]

    def __str__(self):
        return f"{pick_translation(self.label, 'uz')} ({self.key})"

class ProSubscription(models.Model):
    """Patient ning aktiv Pro obunasi"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pro_subscriptions",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="pro_subscriptions",
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(
        ProPlan, on_delete=models.SET_NULL, null=True, related_name="subscriptions"
    )
    plan_snapshot = models.JSONField(
        default=dict, help_text="Plan nomi/narxi/muddati sotib olingan paytdagi nusxasi"
    )
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    payment = models.OneToOneField(
        "Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pro_subscription",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "expires_at"]),
        ]

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "user")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} — Pro until {self.expires_at:%Y-%m-%d}"

    @property
    def is_active(self):
        return self.expires_at > timezone.now()


# --- Doctor tariflari ---
