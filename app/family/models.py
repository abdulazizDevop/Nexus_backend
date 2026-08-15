"""Oila a'zosi ↔ bemor bog'lanishi.

Bemor oila a'zosini telefon raqami bo'yicha taklif qiladi; a'zo qabul qilgach
bemorning kuzatuv ma'lumotlarini (muolaja, ko'rsatkichlar, kayfiyat, AI
hisobotlar) FAQAT O'QISH rejimida ko'ra oladi. Shifokor va AI bilan birga
uchinchi kuzatuvchi tomon.

Pattern: app/doctors.DoctorPatient (self-contained — coupling yo'q).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from app.users.models import Patient


class FamilyLink(models.Model):
    """Bemor → oila a'zosi bog'lanishi (taklif → qabul/rad → bekor)."""

    class Relation(models.TextChoices):
        FARZAND = "child", "Farzand"
        OTA_ONA = "parent", "Ota-ona"
        TURMUSH_ORTOGI = "spouse", "Turmush o'rtog'i"
        AKA_UKA = "sibling", "Aka-uka / opa-singil"
        BOSHQA = "other", "Boshqa"

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        ACCEPTED = "accepted", "Qabul qilingan"
        DECLINED = "declined", "Rad etilgan"
        REVOKED = "revoked", "Bekor qilingan"

    # Kuzatilayotgan bemor (taklif yuboruvchi)
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_links",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="family_links",
        null=True,
        blank=True,
    )
    # Kuzatuvchi oila a'zosi (taklifni qabul qiluvchi)
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_memberships",
    )
    relation = models.CharField(
        max_length=10, choices=Relation.choices, default=Relation.BOSHQA,
        help_text="A'zoning bemorga nisbatan kimligi (bemor belgilaydi)",
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "member"], name="uniq_family_link"
            ),
        ]
        indexes = [
            models.Index(fields=["member", "status"]),
            models.Index(fields=["patient", "status"]),
        ]

    def save(self, *args, **kwargs):
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def mark_responded(self, status: str):
        self.status = status
        self.responded_at = timezone.now()
        self.save(update_fields=["status", "responded_at"])

    def __str__(self):
        return f"{self.patient} ← {self.member} ({self.get_status_display()})"


def member_can_access_patient(member_user, patient_user_id) -> bool:
    """A'zo shu bemorni kuzatishga ruxsatlimi (ACCEPTED bog'lanish bormi)?"""
    return FamilyLink.objects.filter(
        member=member_user,
        patient_id=patient_user_id,
        status=FamilyLink.Status.ACCEPTED,
    ).exists()


def family_member_user_ids(patient_user_id) -> list[int]:
    """Bemorning ACCEPTED oila a'zolari User.id ro'yxati (alert fan-out uchun)."""
    return list(
        FamilyLink.objects.filter(
            patient_id=patient_user_id, status=FamilyLink.Status.ACCEPTED
        ).values_list("member_id", flat=True)
    )
