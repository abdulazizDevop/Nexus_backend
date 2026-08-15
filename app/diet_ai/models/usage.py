from .common import *  # noqa: F401,F403
from .common import _patient_profile_id_for  # underscore (star bermaydi)


class DietDailyUsage(models.Model):
    """Kunlik ishlatish (bepul userlar uchun 10 ta savol/kun).

    Pro userlar bu tekshiruvdan o'tmaydi — cheksiz.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="diet_usage",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="diet_usage",
        null=True,
        blank=True,
    )
    date = models.DateField()
    questions_count = models.PositiveIntegerField(default=0)
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("user", "date")]
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "-date"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            self.patient_profile_id = _patient_profile_id_for(self.user_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user_id} {self.date}: {self.questions_count} savol"
