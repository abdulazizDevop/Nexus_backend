"""Health AI modellari.

  - AIHealthReport            — kunlik AI insight hisoboti (DOCTOR uchun, bemorga ketmaydi)
  - AiConversation / AiMessage — doctor↔AI chat (bemor bo'yicha savol-javob)

Pattern: app/diet_ai/models.py (self-contained — coupling yo'q). Yangi profile-ID
maydonlari ishlatiladi (patient_profile, doctor_profile) — CLAUDE.md qoidasi.
"""

from django.conf import settings
from django.db import models

LANG_CHOICES = [("uz", "O'zbek"), ("uz-cyrl", "Ўзбек"), ("ru", "Русский")]


class AIHealthReport(models.Model):
    """Kunlik AI insight hisoboti — SHIFOKOR uchun (06:00 Celery generatsiya).

    Bemorning so'nggi ma'lumotlaridan (ko'rsatkich trendi + ovqat-log xulqi +
    parhez + muolaja adherence + engagement) AI insight. Bemorga KETMAYDI.
    Bir bemor+doctor+kun uchun bitta (unique — idempotent).
    """

    class Severity(models.TextChoices):
        NORMAL = "normal", "Normal"
        ATTENTION = "attention", "E'tibor talab"
        CRITICAL = "critical", "Jiddiy"

    patient_profile = models.ForeignKey(
        "users.Patient", on_delete=models.CASCADE, related_name="ai_health_reports"
    )
    # Kontekst so'rovlari (HealthIndicator.user_id va h.k.) User bo'yicha ketadi.
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_health_reports"
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile", on_delete=models.CASCADE, related_name="ai_health_reports"
    )

    period_start = models.DateField(help_text="Hisobot kuni")
    period_end = models.DateField(help_text="Tahlil oynasi oxiri")

    summary = models.TextField(blank=True, help_text="AI umumiy insight (2-4 jumla)")
    detected_changes = models.JSONField(
        default=list, blank=True, help_text="Aniqlangan o'zgarishlar/insightlar ro'yxati"
    )
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.NORMAL
    )

    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)
    seen_at = models.DateTimeField(null=True, blank=True, help_text="Doctor o'qigan vaqt")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["patient_profile", "doctor", "period_start"],
                name="uniq_daily_ai_report",
            )
        ]
        indexes = [
            models.Index(fields=["doctor", "-period_start"]),
            models.Index(fields=["doctor", "severity", "-period_start"]),
        ]

    def __str__(self):
        return f"AIReport(doctor={self.doctor_id}, patient={self.patient_id}, {self.period_start}, {self.severity})"


class AiConversation(models.Model):
    """Shifokor↔AI suhbat — bitta bemor bo'yicha (doctor savol beradi)."""

    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile", on_delete=models.CASCADE, related_name="ai_conversations"
    )
    patient_profile = models.ForeignKey(
        "users.Patient", on_delete=models.CASCADE,
        related_name="ai_conversations", null=True, blank=True,
    )
    # Kontekst (build_patient_context) User oladi.
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        related_name="ai_conversations_about", null=True, blank=True,
    )
    title = models.CharField(max_length=200, blank=True)
    language = models.CharField(max_length=10, default="uz", choices=LANG_CHOICES)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["doctor_profile", "patient_profile", "-updated_at"]),
        ]

    def __str__(self):
        return f"AiConvo(doctor={self.doctor_profile_id}, patient={self.patient_profile_id}: {self.title or 'suhbat'})"


class AiMessage(models.Model):
    """Doctor↔AI suhbat xabari."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    conversation = models.ForeignKey(
        AiConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField(blank=True)
    metadata = models.JSONField(blank=True, null=True)
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"
