from .common import *  # noqa: F401,F403


class ChatAIDailyUsage(models.Model):
    """AI gatekeeper kunlik hisoblagich — har (bemor, doctor) juftligiga.

    Tarifsiz bemorga AI avto-javoblari soni cheklanadi (Gemini xarajati + abuse).
    Limit: SystemSetting["chat_ai_daily_cap"] (default 10). diet_ai DietDailyUsage
    namunasidagi atomic-upsert pattern bilan oshiriladi.
    """

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_ai_usage",
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="chat_ai_usage",
    )
    date = models.DateField()
    replies_count = models.PositiveIntegerField(default=0)
    tokens_input = models.PositiveIntegerField(default=0)
    tokens_output = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("patient", "doctor", "date")]
        indexes = [
            models.Index(fields=["patient", "doctor", "date"]),
        ]

    def __str__(self):
        return f"{self.patient_id}→{self.doctor_id} {self.date}: {self.replies_count}"
