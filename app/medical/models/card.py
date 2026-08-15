from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_doctor_profile, _autofill_patient_profile  # underscore helper (star bermaydi)

class MedicalCard(models.Model):
    """Bemorning umumiy tibbiy kartasi (1:1 User)."""

    class BloodType(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    class Status(models.TextChoices):
        GOOD = "good", "Yaxshi"
        NORMAL = "normal", "O'rta"
        BAD = "bad", "Yomon"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="medical_card",
    )
    patient_profile = models.OneToOneField(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="medical_card",
        null=True,
        blank=True,
    )
    blood_type = models.CharField(max_length=4, choices=BloodType.choices, blank=True)
    # Antropometriya — yagona manba (diet profil shu yerdan o'qiydi/yozadi).
    height_cm = models.PositiveIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    primary_disease = models.CharField(max_length=255, blank=True)
    current_status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.NORMAL
    )
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_medical_cards",
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_medical_cards",
        help_text="Kartani yangilangan doctor (admin yangilagan bo'lsa null).",
    )

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "user")
        _autofill_doctor_profile(self, "updated_by")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"MedicalCard({self.user})"
