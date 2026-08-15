from .common import *  # noqa: F401,F403
from .common import _patient_profile_id_for  # underscore (star bermaydi)


HAS_IMAGE = Q(image_key__isnull=False) & ~Q(image_key="")


class DietMessageQuerySet(models.QuerySet):
    def with_image(self):
        """Faqat ovqat rasmi biriktirilgan xabarlar."""
        return self.filter(HAS_IMAGE)


class DietConversation(models.Model):
    """Bemor bilan AI o'rtasidagi bitta suhbat (topic bo'yicha alohida)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="diet_conversations",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="diet_conversations",
        null=True,
        blank=True,
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        help_text="Avto generatsiya qilinadi (birinchi savoldan) yoki user yangilaydi",
    )
    language = models.CharField(
        max_length=10,
        default="uz",
        choices=[("uz", "O'zbek"), ("uz-cyrl", "Ўзбек"), ("ru", "Русский")],
    )
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            self.patient_profile_id = _patient_profile_id_for(self.user_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_id}: {self.title or 'Suhbat'}"


class DietMessage(models.Model):
    """Suhbat ichidagi har bir xabar."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        DietConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField(blank=True)
    image_key = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="DO Spaces key (ovqat rasmi bo'lsa)",
    )
    metadata = models.JSONField(
        blank=True,
        null=True,
        help_text="Qo'shimcha ma'lumot: food_name, portion, grams, pieces, calories",
    )
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)
    is_blocked = models.BooleanField(
        default=False,
        help_text="Xatarli savol bloklangan bo'lsa True (guardrail)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = DietMessageQuerySet.as_manager()

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"


class DietEntry(models.Model):
    """Kunlik parhez yozuvi — bitta taom (manual kiritilgan yoki AI tahlilidan).

    Har yozuv alohida saqlanadi — HealthIndicator accumulate bo'lganda har taomni
    aniq ayirish/o'chirish uchun.

    Qachon yaratiladi:
      - Manual input: POST /diet/manual-entry/
      - AI confirm: POST /diet/messages/{id}/confirm-calories/

    Delete qilinganda: HealthIndicator.value dan ayiriladi (atomic).
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Qo'lda"
        AI_PHOTO = "ai_photo", "AI rasmi"
        AI_TEXT = "ai_text", "AI matn"

    class MealType(models.TextChoices):
        BREAKFAST = "breakfast", "Nonushta"
        LUNCH = "lunch", "Tushlik"
        DINNER = "dinner", "Kechki"
        SNACK = "snack", "Gazak"

    class GlycemicLoad(models.TextChoices):
        LOW = "low", "Past"
        MEDIUM = "medium", "O'rta"
        HIGH = "high", "Yuqori"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="diet_entries",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="diet_entries",
        null=True,
        blank=True,
    )
    date = models.DateField()
    food_name = models.CharField(max_length=200)
    calories = models.PositiveIntegerField(default=0)
    carbs_grams = models.PositiveIntegerField(default=0)
    protein_grams = models.PositiveIntegerField(default=0)
    fat_grams = models.PositiveIntegerField(default=0)
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.MANUAL
    )
    meal_type = models.CharField(
        max_length=10,
        choices=MealType.choices,
        blank=True,
        null=True,
        help_text="Ovqatlanish mahali; berilmasa created_at soatidan aniqlanadi",
    )
    glycemic_load = models.CharField(
        max_length=6,
        choices=GlycemicLoad.choices,
        blank=True,
        null=True,
        help_text="AI baholagan glikemik yuk (diabet/surunkali kasallik nazorati)",
    )
    portion_grams = models.PositiveIntegerField(null=True, blank=True)
    ingredients = models.JSONField(
        default=list,
        blank=True,
        help_text="[{name, grams, calories, carbs_g, protein_g, fat_g}] — tahrirlanadi",
    )
    ai_message = models.ForeignKey(
        DietMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
        help_text="Agar AI confirm orqali yaratilgan bo'lsa",
    )
    image_key = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Ovqat rasmi DO Spaces key (AI photo-dan yoki manual upload)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["user", "-date"]),
            models.Index(fields=["user", "date", "source"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            self.patient_profile_id = _patient_profile_id_for(self.user_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_id} {self.date}: {self.food_name} ({self.calories} kcal)"
