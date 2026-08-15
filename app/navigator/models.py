"""Navigator AI chat suhbatlari (kontrakt §8).

Tashxis va roadmap ma'lumotlari app/medical'da (MedicalCondition, RoadmapStep) —
bu app API qatlami + chat saqlash. Pattern: app/health_ai (self-contained).
"""

from django.conf import settings
from django.db import models

from app.users.models import Patient


class NavConversation(models.Model):
    """Bemor ↔ navigator AI suhbati (kontraktda conversation_id = "c-{id}")."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="nav_conversations",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="nav_conversations",
        null=True,
        blank=True,
    )
    diagnosis = models.ForeignKey(
        "medical.MedicalCondition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="nav_conversations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.user_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    @property
    def public_id(self) -> str:
        return f"c-{self.pk}"


class NavMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Bemor"
        ASSISTANT = "assistant", "AI"

    conversation = models.ForeignKey(
        NavConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
