from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_doctor_profile, _autofill_patient_profile  # underscore helper (star bermaydi)

class MedicalNote(models.Model):
    """Shifokor yozuvi (kunlik kuzatuv)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="medical_notes",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="medical_notes",
        null=True,
        blank=True,
    )
    text = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="written_notes",
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="written_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "user")
        _autofill_doctor_profile(self, "created_by")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Note({self.user}, {self.created_at:%Y-%m-%d})"

class MedicalNoteImage(models.Model):
    """MedicalNote ga ilova qilingan rasm. Bir yozuvda bir nechta bo'la oladi."""

    note = models.ForeignKey(
        MedicalNote, on_delete=models.CASCADE, related_name="images"
    )
    file_key = models.CharField(
        max_length=500,
        help_text="DO Spaces S3 key. Frontend Bunny CDN signed URL orqali ochadi.",
    )
    file_mime = models.CharField(max_length=80, blank=True)
    file_size_bytes = models.BigIntegerField(null=True, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    order = models.IntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "uploaded_at"]
        indexes = [
            models.Index(fields=["note", "order"]),
        ]

    def __str__(self):
        return f"NoteImage({self.note_id}, {self.original_name or self.file_key})"


# --- Analizlar (Analysis prescriptions + results) ---
