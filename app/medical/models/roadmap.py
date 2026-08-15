from .common import *  # noqa: F401,F403
from .common import _autofill_patient_profile

from .condition import MedicalCondition


class RoadmapStep(models.Model):
    """Tashxisdan keyingi yo'l xaritasi qadami (Sog'liq Navigator).

    Har qadam bitta MedicalCondition (tashxis)ga bog'lanadi. Davrlar:
    birinchi hafta / birinchi oy / doimiy. "Doimiy" qadamlar — odatlar,
    ular "bajarildi" deb yopilmaydi (complete → 400).
    Dori qadami ixtiyoriy ravishda Treatment'ga bog'lanishi mumkin
    (muolaja belgilansa progress muolaja orqali kuzatiladi).
    """

    class Period(models.TextChoices):
        FIRST_WEEK = "first_week", "Birinchi hafta"
        FIRST_MONTH = "first_month", "Birinchi oy"
        ONGOING = "ongoing", "Doimiy"

    class Status(models.TextChoices):
        PENDING = "pending", "Bajarilmagan"
        COMPLETED = "completed", "Bajarilgan"

    condition = models.ForeignKey(
        MedicalCondition,
        on_delete=models.CASCADE,
        related_name="roadmap_steps",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roadmap_steps",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="roadmap_steps",
        null=True,
        blank=True,
    )
    period = models.CharField(max_length=15, choices=Period.choices)
    order = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    specialist = models.CharField(
        max_length=100, blank=True,
        help_text="Mutaxassis chipi (Kardiolog, Laboratoriya...). Bo'sh = o'z-o'ziga qadam",
    )
    treatment = models.ForeignKey(
        "treatment.Treatment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roadmap_steps",
        help_text="Dori qadami muolajaga bog'langan bo'lsa",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["period", "order", "id"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["condition", "period"]),
        ]

    def save(self, *args, **kwargs):
        if self.condition_id and not self.user_id:
            self.user_id = self.condition.user_id
        _autofill_patient_profile(self, "user")
        super().save(*args, **kwargs)

    @property
    def is_habit(self) -> bool:
        """Doimiy qadam — odat, "bajarildi" deb yopilmaydi."""
        return self.period == self.Period.ONGOING

    def __str__(self):
        return f"[{self.get_period_display()}] {self.title}"
