from .common import *  # noqa: F401,F403


class DietRestriction(models.Model):
    """Doctor bemor uchun qo'ygan parhez cheklovi.

    Example: "shakarsiz", "kam tuz", "glyuten-free", "laktozasiz"
    Har AI so'rovda system prompt'ga qo'shiladi.
    """

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="diet_restrictions",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="diet_restrictions",
        null=True,
        blank=True,
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diet_restrictions_set",
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diet_restrictions_set",
    )
    rule = models.CharField(
        max_length=200,
        help_text="Masalan: 'shakarsiz', 'kam tuz', 'glyuten-free'",
    )
    reason = models.TextField(
        blank=True,
        help_text="Sabab (ixtiyoriy, bemorga ham ko'rsatiladi)",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "is_active"]),
        ]

    def save(self, *args, **kwargs):
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        if self.doctor_id and not self.doctor_profile_id:
            dp = DoctorProfile.objects.filter(user_id=self.doctor_id).first()
            if dp:
                self.doctor_profile = dp
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient_id}: {self.rule}"
