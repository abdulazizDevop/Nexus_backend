from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from app.users.models import Patient

REVIEW_EDIT_WINDOW_HOURS = 24
REVIEW_COOLDOWN_DAYS = 30
POSITIVE_MIN_RATING = 4  # 4-5 yulduz — Ijobiy
CRITICAL_MAX_RATING = 3  # 1-3 yulduz — Tanqidiy


class ReviewTag(models.Model):
    """Oldindan belgilangan review taglari (admin boshqaradi).

    Patient review yozayotganda yulduz raytingiga qarab ijobiy yoki salbiy
    taglar ko'rsatiladi. Tag tanlash — multi-select.
    """

    class Sentiment(models.TextChoices):
        POSITIVE = "positive", "Ijobiy"
        NEGATIVE = "negative", "Salbiy"

    slug = models.SlugField(unique=True, max_length=64)
    label_uz = models.CharField(max_length=80)
    label_ru = models.CharField(max_length=80, blank=True)
    sentiment = models.CharField(max_length=10, choices=Sentiment.choices)
    icon = models.CharField(max_length=10, blank=True, help_text="Emoji yoki belgi")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sentiment", "order", "id"]
        indexes = [
            models.Index(fields=["sentiment", "is_active"]),
        ]

    def __str__(self):
        return f"[{self.sentiment}] {self.label_uz}"

    @staticmethod
    def sentiment_for_rating(rating):
        """Rating'ga mos sentiment: 4-5 → positive, 1-3 → negative."""
        return (
            ReviewTag.Sentiment.POSITIVE
            if rating >= POSITIVE_MIN_RATING
            else ReviewTag.Sentiment.NEGATIVE
        )


class Review(models.Model):
    """Doctor uchun bemor reviewi.

    Qoidalar:
      - Faqat appointment status=COMPLETED bo'lgan bemor yoza oladi
      - Bir appointment uchun bitta review (OneToOne)
      - Patient yozilgandan 24 soat ichida tahrirlay yoki o'chira oladi
      - 24 soat o'tgach review qotib qoladi
    """

    appointment = models.OneToOneField(
        "meetings.Appointment",
        on_delete=models.CASCADE,
        related_name="review",
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="reviews",
        null=True,
        blank=True,
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 dan 5 gacha yulduz",
    )
    comment = models.TextField(blank=True, max_length=1000)
    tags = models.ManyToManyField(ReviewTag, blank=True, related_name="reviews")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.patient.full_name} → Dr.{self.doctor.user.full_name}: {self.rating}⭐"

    @property
    def edit_window_open(self) -> bool:
        if not self.created_at:
            return True
        return timezone.now() < self.created_at + timedelta(hours=REVIEW_EDIT_WINDOW_HOURS)

    def clean(self):
        from app.meetings.models import Appointment

        if not self.appointment_id:
            return

        appt = self.appointment

        if appt.status != Appointment.Status.COMPLETED:
            raise ValidationError(
                {"appointment": "Faqat yakunlangan qabul uchun review qoldirish mumkin."}
            )

        # Himoya: normal create yo'lida save() bu maydonlarni appointment'dan
        # to'ldiradi, shuning uchun mos kelmaslik faqat admin/shell orqali qo'lda
        # noto'g'ri qiymat berilganda yuzaga keladi.
        if self.patient_id and self.patient_id != appt.patient_id:
            raise ValidationError(
                {"patient": "Patient appointmentdagi patient bilan mos kelmaydi."}
            )
        if self.doctor_id and self.doctor_id != appt.doctor_id:
            raise ValidationError(
                {"doctor": "Doctor appointmentdagi doctor bilan mos kelmaydi."}
            )

    def save(self, *args, **kwargs):
        is_new = not self.pk
        if self.appointment_id and is_new:
            self.doctor_id = self.appointment.doctor_id
            self.patient_id = self.appointment.patient_id
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        # Yangi obyekt uchun himoya validatsiyasi. Update'lar serializer orqali
        # validatsiya qilinadi, shuning uchun har save'da takror full_clean kerak emas.
        if is_new:
            self.full_clean()
        super().save(*args, **kwargs)
