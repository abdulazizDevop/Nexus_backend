from .common import *  # noqa: F401,F403


class PrescriptionScan(models.Model):
    """Tashxis/retsept qog'ozi skani — AI tahlili + bemor tasdig'i oqimi.

    Flow: rasm yuklanadi → Gemini vision qog'ozdagi muolajalarni o'qiydi →
    scan `pending_review` holatida takliflar bilan saqlanadi → bemor ko'rib
    tasdiqlasa (tahrir qilishi ham mumkin) Treatment yozuvlari yaratiladi.
    AI hech narsa TO'QIMAYDI — faqat qog'ozda yozilganini ko'chiradi,
    o'qib bo'lmagan joylar warnings'da qaytadi.
    """

    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Tasdiqlash kutilmoqda"
        CONFIRMED = "confirmed", "Tasdiqlangan"
        DISCARDED = "discarded", "Rad etilgan"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prescription_scans",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="prescription_scans",
        null=True,
        blank=True,
    )
    image_key = models.CharField(max_length=500, help_text="DO Spaces'dagi rasm kaliti")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW
    )
    summary = models.TextField(
        blank=True, help_text="AI qisqacha izohi (qog'ozda nima yozilgani)"
    )
    ai_items = models.JSONField(
        default=list, blank=True,
        help_text="AI taklif qilgan muolajalar [{title, type, dosage, times, repeat, ...}]",
    )
    ai_warnings = models.JSONField(
        default=list, blank=True,
        help_text="O'qib bo'lmagan/noaniq joylar haqida ogohlantirishlar",
    )
    created_treatment_ids = models.JSONField(
        default=list, blank=True,
        help_text="Tasdiqlangach yaratilgan Treatment id'lari",
    )
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.user_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def __str__(self):
        return f"PrescriptionScan #{self.pk} {self.user} [{self.status}]"
