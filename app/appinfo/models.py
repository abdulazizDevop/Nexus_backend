from django.db import models

from core.i18n import pick_translation


class MobileAppInfo(models.Model):
    """Mobil ilova versiya / yangilanish konfiguratsiyasi — admin boshqaradi.

    Har app uchun BITTA qator (patient, doctor). Mobil `GET /info/mobile/` orqali
    oladi va versiya/yangilanish bannerini ko'rsatadi:
      - `update_available` → yumshoq banner ("yangilanish bor", keyinroq qilsa bo'ladi)
      - `force_update`     → majburiy (eski versiyani bloklaydi)
      - `min_version`      → undan pastrog'i majburiy yangilanadi (mobil solishtiradi)
    `title`/`message` — 3 tilli (so'rovning `?lang=` siga qarab string qaytadi).
    """

    class AppScope(models.TextChoices):
        PATIENT = "patient", "Patient app"
        DOCTOR = "doctor", "Doctor app"

    app_scope = models.CharField(
        max_length=10, choices=AppScope.choices, unique=True
    )
    latest_version = models.CharField(
        max_length=20, blank=True, help_text="Eng yangi versiya, masalan 1.4.2"
    )
    min_version = models.CharField(
        max_length=20,
        blank=True,
        help_text="Minimal qo'llab-quvvatlanadigan versiya — pastrog'i majburiy yangilanadi",
    )
    update_available = models.BooleanField(
        default=False, help_text="Yumshoq banner — 'yangilanish bor'"
    )
    force_update = models.BooleanField(
        default=False, help_text="Majburiy — eski versiyani bloklaydi"
    )
    title = models.JSONField(default=dict, blank=True, help_text="3 tilli sarlavha {uz,ru,cyr}")
    message = models.JSONField(default=dict, blank=True, help_text="3 tilli matn {uz,ru,cyr}")
    ios_url = models.URLField(blank=True, help_text="App Store havolasi (Yangilash tugmasi)")
    android_url = models.URLField(blank=True, help_text="Play Store havolasi")
    is_active = models.BooleanField(
        default=True, help_text="False → mobil hech qanday banner ko'rsatmaydi"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["app_scope"]

    @property
    def title_uz(self) -> str:
        return pick_translation(self.title, "uz")

    def __str__(self):
        return f"MobileAppInfo[{self.app_scope}] v{self.latest_version or '-'}"
