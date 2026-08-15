from .common import *  # noqa: F401,F403


class DailySituationCheckup(models.Model):
    class Status(models.TextChoices):
        GOOD = "good", "Yaxshi"
        NORMAL = "normal", "O'rtacha"
        BAD = "bad", "Yomon"

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="situation_checkups",
        null=True,
        blank=True,
    )
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=Status.choices)
    note = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "date"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.user_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} - {self.date} - {self.get_status_display()}"
