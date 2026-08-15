from .common import *  # noqa: F401,F403


class DailyCalorieLimit(models.Model):
    """Doctor belgilaydigan kunlik kaloriya + macros chegaralari"""

    patient = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="calorie_limit",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="calorie_limits",
        null=True,
        blank=True,
    )
    calories = models.PositiveIntegerField(help_text="Kunlik kaloriya chegarasi (kcal)")
    carbs_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Kunlik uglevod chegarasi (g)"
    )
    protein_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Kunlik oqsil chegarasi (g)"
    )
    fat_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Kunlik yog' chegarasi (g)"
    )
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="set_calorie_limits",
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="set_calorie_limits",
    )
    notes = models.TextField(blank=True, help_text="Doctor izohi")
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        if self.set_by_id and not self.doctor_profile_id:
            dp = DoctorProfile.objects.filter(user_id=self.set_by_id).first()
            if dp:
                self.doctor_profile = dp
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient.full_name}: {self.calories} kcal/kun"
