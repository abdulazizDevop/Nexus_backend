from .common import *  # noqa: F401,F403


class HealthIndicatorType(models.Model):
    """Ko'rsatkich turlari — admin tomonidan yaratiladi.

    `name` 3 tilli JSON (ko'rinish). Diet AI ishlatadigan macros turlari
    `system_key` bilan belgilanadi (stable identifier — string matching va
    tarjima muammolaridan mustaqil):

      system_key="calories" — kaloriya
      system_key="carbs"    — uglevod
      system_key="protein"  — oqsil
      system_key="fat"      — yog'

    `category` (manual/diet) UI'da turning joyini belgilaydi — API
    BARCHA turlarni qaytaradi, client/UI `category` + `manual_entry` flag'lari
    bo'yicha filtrlaydi (kodda nom/system_key taxmini o'rniga aniq belgilash).
    """

    # Diet AI macro `system_key` qiymatlari. Admin yangi user-facing type
    # yaratganda shu nomlardan birini ishlatib bo'lmaydi (UI'da chalkashlik
    # bo'lmasligi uchun).
    SYSTEM_NAMES = ("Kaloriya", "Uglevod", "Oqsil", "Yog'")
    SYSTEM_KEYS = ("calories", "carbs", "protein", "fat")

    class ValueFormat(models.TextChoices):
        NUMBER = "number", "Bitta son"
        RANGE = "range", "Ikki son (masalan qon bosimi 120/80)"

    class Category(models.TextChoices):
        MANUAL = "manual", "Qo'lda kiritiladigan"
        DIET = "diet", "Ovqat (Diet AI)"

    name = models.JSONField(default=dict)
    system_key = models.CharField(
        max_length=20, null=True, blank=True, unique=True,
        help_text="Diet AI macros uchun stable ID. Oddiy turlarda bo'sh.",
    )
    unit = models.CharField(max_length=20, blank=True)
    icon = models.CharField(max_length=50, blank=True)
    value_format = models.CharField(
        max_length=10,
        choices=ValueFormat.choices,
        default=ValueFormat.NUMBER,
        help_text="number = bitta qiymat (vazn, harorat). range = ikki qiymat (qon bosimi).",
    )
    category = models.CharField(
        max_length=10,
        choices=Category.choices,
        default=Category.MANUAL,
        help_text="UI shu flag bo'yicha turni joylashtiradi: manual=qo'lda dialog, "
                  "diet=Diet AI. Taxmin emas — aniq belgilanadi.",
    )
    manual_entry = models.BooleanField(
        default=True,
        help_text="False bo'lsa qo'lda qo'shish dialogida ko'rinmaydi "
                  "(masalan, faqat tizim yozadigan turlar uchun).",
    )

    @property
    def name_uz(self) -> str:
        return pick_translation(self.name, "uz")

    @property
    def is_system(self) -> bool:
        return bool(self.system_key)

    def __str__(self):
        return f"{self.name_uz} ({self.unit})" if self.unit else (self.name_uz or "(no name)")


class HealthIndicator(models.Model):
    """Patient salomatlik ko'rsatkichlari — event sourcing.

    Har yozuv = bitta event (ovqat yoki qo'lda kiritilgan o'lchov).
    Kunlik jami `aggregate(Sum("value"))` orqali olinadi. `date` `recorded_at`'dan
    avto-hisoblanadi — sanaga ko'ra tez filter qilish uchun saqlanadi.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Qo'lda"
        DIET_AI = "diet_ai", "Ovqat (Diet AI)"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="health_indicators"
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="health_indicators",
        null=True,
        blank=True,
    )
    indicator_type = models.ForeignKey(HealthIndicatorType, on_delete=models.CASCADE)
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Asosiy qiymat (range bo'lsa systolic)",
    )
    value_secondary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ikkinchi qiymat (faqat range tipi uchun, masalan diastolic)",
    )
    recorded_at = models.DateTimeField(
        default=timezone.now,
        help_text="O'lchov vaqti (kiritilgan vaqt)",
    )
    date = models.DateField(
        db_index=True,
        help_text="recorded_at'dan avto-hisoblanadi (kunlik query'lar uchun)",
    )
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.MANUAL,
    )
    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text="Uyqu uchun stages, va boshqa ixtiyoriy ma'lumotlar",
    )

    class Meta:
        ordering = ["-recorded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "indicator_type", "recorded_at", "source"],
                name="health_indicator_unique_event",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "indicator_type", "recorded_at"]),
            # Kunlik agregatsiya — GROUP BY date tez bo'lsin.
            models.Index(fields=["user", "indicator_type", "date"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.user_id)
            self.patient_profile = patient_profile
        if self.recorded_at and not self.date:
            self.date = timezone.localtime(self.recorded_at).date()
        if self.meta is None:
            self.meta = {}
        super().save(*args, **kwargs)

    def __str__(self):
        # indicator_type.name JSONField — pick_translation bilan uz default
        name = pick_translation(self.indicator_type.name, "uz")
        if self.value_secondary is not None:
            return f"{self.user} - {name}: {self.value}/{self.value_secondary} ({self.date})"
        return f"{self.user} - {name}: {self.value} ({self.date})"

    @property
    def display_value(self):
        """Frontend ko'rsatish uchun formatlangan qiymat."""
        if self.value_secondary is not None:
            return f"{self.value}/{self.value_secondary}"
        return str(self.value)
