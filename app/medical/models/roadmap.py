from .common import *  # noqa: F401,F403
from .common import _autofill_patient_profile

from .condition import MedicalCondition


class RoadmapStep(models.Model):
    """Navigator yo'l xaritasi qadami (ai_navigator_api_contract.md §0, §2).

    Qadamlar KETMA-KET: `order` bo'yicha bittasi `current`, keyingilari
    `locked` — oldingi qadam bajarilgach ochiladi. Har qadam tur (`type`)
    bo'yicha mobil tomonda alohida harakatga ulanadi (payload orqali).
    """

    class Type(models.TextChoices):
        MEDICATION = "medication", "Dori qabul qilish"
        ANALYSIS = "analysis", "Analiz topshirish"
        CONSULTATION = "consultation", "Shifokorga murojaat"
        LIFESTYLE = "lifestyle", "Turmush tarzi / parhez"
        CHECKUP = "checkup", "Nazorat ko'rigi"
        EDUCATION = "education", "Tushuntirish / o'qish"

    class Status(models.TextChoices):
        DONE = "done", "Bajarilgan"
        CURRENT = "current", "Hozir bajarilishi kerak"
        LOCKED = "locked", "Yopiq"
        SKIPPED = "skipped", "O'tkazib yuborilgan"

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
    order = models.PositiveSmallIntegerField(default=1)
    type = models.CharField(max_length=15, choices=Type.choices)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.LOCKED
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    body = models.TextField(
        blank=True, help_text="education qadam uchun to'liq matn (sheet'da ochiladi)"
    )
    due_date = models.DateField(null=True, blank=True)
    payload = models.JSONField(
        null=True, blank=True,
        help_text="Tur-ga bog'liq ma'lumot (kontrakt §2 payload qoidalari)",
    )
    treatment = models.ForeignKey(
        "treatment.Treatment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roadmap_steps",
        help_text="medication qadamidan yaratilgan muolaja (bo'lsa)",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["condition", "order"]),
        ]

    def save(self, *args, **kwargs):
        if self.condition_id and not self.user_id:
            self.user_id = self.condition.user_id
        _autofill_patient_profile(self, "user")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"#{self.order} [{self.get_type_display()}] {self.title}"
