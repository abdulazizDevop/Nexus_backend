from django.db import models

from core.i18n import pick_translation


class GuideVideo(models.Model):
    """Video qo'llanma — admin panel orqali boshqariladi, mobil `GET /guides/`
    orqali oladi va ilova ichidagi brauzerda ochadi.

    `title`/`description`/`video_url` — 3 tilli JSON ({"uz","ru","cyr"}). So'rov
    tiliga (`?lang=`) qarab string qaytadi, tarjima bo'sh bo'lsa `uz` ga fallback
    (`TranslatableFieldsMixin`). Odatda bitta o'zbek video — faqat `uz` to'ldiriladi.
    """

    class AppScope(models.TextChoices):
        DOCTOR = "doctor", "Doctor app"
        PATIENT = "patient", "Patient app"
        BOTH = "both", "Ikkalasi"

    class Category(models.TextChoices):
        GETTING_STARTED = "getting_started", "Boshlash"
        FEATURES = "features", "Imkoniyatlar"
        BILLING = "billing", "To'lov"
        OTHER = "other", "Boshqa"

    title = models.JSONField(default=dict, help_text="3 tilli sarlavha {uz,ru,cyr}")
    description = models.JSONField(
        default=dict, blank=True, help_text="3 tilli qisqa tavsif (ixtiyoriy)"
    )
    video_url = models.JSONField(
        default=dict, help_text="YouTube havola (3 tilli, odatda faqat uz)"
    )
    thumbnail_url = models.URLField(
        blank=True,
        help_text="Ixtiyoriy. Bo'sh bo'lsa mobil YouTube'dan avtomatik yasaydi.",
    )
    duration_seconds = models.PositiveIntegerField(
        null=True, blank=True, help_text="Ixtiyoriy — '2:30' ko'rsatish uchun"
    )
    app_scope = models.CharField(
        max_length=10,
        choices=AppScope.choices,
        default=AppScope.BOTH,
        help_text="Qaysi ilovaga tegishli (doctor/patient/both)",
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
        help_text="Ro'yxat ekrani bo'limi (kelajak)",
    )
    order = models.PositiveIntegerField(default=0, help_text="Tartib (kichik → tepada)")
    is_active = models.BooleanField(
        default=True, help_text="False → mobil ro'yxatda qaytmaydi (yashiriladi)"
    )
    is_featured = models.BooleanField(
        default=False, help_text="Bosh sahifa banneri uchun"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["app_scope", "is_active", "order"]),
        ]

    @property
    def title_uz(self) -> str:
        return pick_translation(self.title, "uz")

    def __str__(self):
        return f"{self.title_uz or '(no title)'} [{self.app_scope}]"
