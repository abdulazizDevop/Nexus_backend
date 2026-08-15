"""Tracking AI — bemorni AI kuzatib boradi (shifokor va oila a'zosi bilan birga).

health_ai'dan farqi: hisobot BEMOR-markazli (shifokor jufti emas) va bemorning
o'ziga ham ko'rinadi. Kirish huquqi: bemorning o'zi, ACCEPTED shifokorlari va
ACCEPTED oila a'zolari.

Pattern: app/health_ai (self-contained — coupling yo'q).
"""

from django.conf import settings
from django.db import models

from app.users.models import Patient


class AITrackingReport(models.Model):
    """Kunlik AI kuzatuv hisoboti — bemor bo'yicha bitta (kun/bemor unique)."""

    class Severity(models.TextChoices):
        NORMAL = "normal", "Normal"
        ATTENTION = "attention", "E'tibor talab"
        CRITICAL = "critical", "Jiddiy"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_tracking_reports",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="ai_tracking_reports",
        null=True,
        blank=True,
    )
    period_start = models.DateField(help_text="Hisobot qamrab olgan kun (boshlanishi)")
    period_end = models.DateField(help_text="Hisobot qamrab olgan kun (tugashi)")
    summary = models.TextField(help_text="AI xulosasi — bemorga tushunarli tilda")
    detected_changes = models.JSONField(
        default=list, blank=True,
        help_text="Aniqlangan o'zgarishlar ro'yxati [{title, description, severity}]",
    )
    recommendations = models.JSONField(
        default=list, blank=True,
        help_text="Bemorga umumiy tavsiyalar (tashxis/dori EMAS) — string ro'yxati",
    )
    adherence_percent = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Muolaja rejasining bajarilishi (%) — hisoblab yoziladi",
    )
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.NORMAL
    )
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)
    seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["patient_profile", "period_start"],
                name="uniq_daily_tracking_report",
            ),
        ]
        indexes = [
            models.Index(fields=["patient", "-period_start"]),
            models.Index(fields=["severity", "-period_start"]),
        ]

    def save(self, *args, **kwargs):
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def __str__(self):
        return f"TrackingAI {self.patient} {self.period_start} [{self.severity}]"
