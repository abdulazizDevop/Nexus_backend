from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_doctor_profile, _autofill_patient_profile  # underscore helper (star bermaydi)

class MedicalCondition(models.Model):
    """Universal kasallik/allergiya/operatsiya/vaksina yozuvi."""

    class Type(models.TextChoices):
        ALLERGY = "allergy", "Allergiya"
        CHRONIC = "chronic", "Surunkali kasallik"
        ACUTE = "acute", "O'tkir kasallik"
        VACCINATION = "vaccination", "Vaksina"
        SURGERY = "surgery", "Operatsiya"
        OTHER = "other", "Boshqa"

    class Severity(models.TextChoices):
        LOW = "low", "Past"
        MEDIUM = "medium", "O'rta"
        HIGH = "high", "Yuqori"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="medical_conditions",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="medical_conditions",
        null=True,
        blank=True,
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    name = models.CharField(max_length=200)
    severity = models.CharField(max_length=10, choices=Severity.choices, blank=True)
    discovered_at = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="added_conditions",
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="added_conditions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-discovered_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "type"]),
        ]

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "user")
        _autofill_doctor_profile(self, "added_by")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_type_display()}: {self.name} ({self.user})"
