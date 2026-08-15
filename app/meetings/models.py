from django.conf import settings
from django.db import models

from app.users.models import Patient


class Appointment(models.Model):
    """Uchrashuv/qabul — patient request yuboradi, doctor tasdiqlaydi"""

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        APPROVED = "approved", "Tasdiqlangan"
        REJECTED = "rejected", "Rad etilgan"
        CANCELLED = "cancelled", "Bekor qilingan"
        COMPLETED = "completed", "Yakunlangan"

    class MeetingType(models.TextChoices):
        ONLINE = "online", "Online"
        OFFLINE = "offline", "Offline"

    class CancelledBy(models.TextChoices):
        PATIENT = "patient", "Bemor"
        DOCTOR = "doctor", "Shifokor"
        ADMIN = "admin", "Admin"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_appointments",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="appointments",
        null=True,
        blank=True,
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="doctor_appointments",
    )

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    meeting_type = models.CharField(
        max_length=10,
        choices=MeetingType.choices,
        default=MeetingType.OFFLINE,
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )

    reason = models.TextField(blank=True, help_text="Bemor murojaat sababi")
    reject_reason = models.TextField(blank=True, help_text="Rad etish sababi")
    notes = models.TextField(
        blank=True, help_text="Doctor izohlari (uchrashuv paytida)"
    )

    cancelled_by = models.CharField(
        max_length=10, blank=True,
        help_text="Bekor qilgan tomon: patient, doctor, admin"
    )

    # LiveKit (online uchun)
    room_name = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-start_time"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["doctor", "date"]),
            models.Index(fields=["status", "date"]),
        ]

    def save(self, *args, **kwargs):
        # Yangi kod patient_profile yubormasa ham, patient (User FK) dan kelib
        # chiqib Patient profilni topib oladi (backward compatible).
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient.full_name} → Dr.{self.doctor.user.full_name} ({self.date} {self.start_time})"


# Slot boshlangach shu daqiqagacha booking/available OCHIQ qoladi (grace) —
# bemor bir-ikki daqiqa kechiksa ham hali vaqt bo'lsa band qila olsin. Uch joy
# shu yagona qiymatga tayanadi (drift yo'q): slots ro'yxati (available), booking
# validatsiyasi (400), to'lanmagan-hold expire (min(TTL, slot_start+grace)).
CONSULTATION_SLOT_GRACE_MIN = 10

# Konsultatsiya tugash vaqtidan shu daqiqa o'tgach CONFIRMED -> COMPLETED (auto,
# Celery beat). Call-oyna (end + CALL_GRACE_MIN=10) allaqachon yopiq bo'lishi uchun
# undan katta. Aks holda konsultatsiya abadiy `confirmed` qolardi.
CONSULTATION_AUTO_COMPLETE_GRACE_MIN = 30


class Consultation(models.Model):
    """Bir martalik pullik video-konsultatsiya (marketplace).

    Appointment'dan FARQLI: to'lov-gate semantikasi. Bemor slot tanlaydi →
    `pending_payment` yaratiladi → to'lov muvaffaqiyatida `confirmed` +
    avto-connect → belgilangan vaqtda LiveKit video → `completed`.
    Appointment (doctor approve/reject semantikasi) KENGAYTIRILMADI — statuslar
    va auto-complete oqimi boshqa; regressiya oldini olish uchun alohida model.
    Slot bilan bog'lanish `doctors.Slot.consultation` OneToOne orqali (bitta
    Slot pool appointment + consultation ikkalasini qamraydi → double-book yo'q).
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "To'lov kutilmoqda"
        CONFIRMED = "confirmed", "Tasdiqlangan"
        COMPLETED = "completed", "Yakunlangan"
        CANCELLED_BY_PATIENT = "cancelled_by_patient", "Bemor bekor qildi"
        CANCELLED_BY_DOCTOR = "cancelled_by_doctor", "Shifokor bekor qildi"
        EXPIRED = "expired", "To'lanmay muddati o'tdi"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_consultations",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="consultations",
        null=True,
        blank=True,
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.CASCADE,
        related_name="doctor_consultations",
    )

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    status = models.CharField(
        max_length=25,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
    )

    # Booking paytidagi narx snapshot'i (doctor keyin narxni o'zgartirsa ham
    # bu xarid o'z summasini saqlaydi).
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # To'lov (universal Payment). pending_payment'da null bo'lishi mumkin
    # (create_payment'dan oldin), keyin bog'lanadi.
    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consultation",
    )

    # LiveKit video xonasi (confirmed'da to'ldiriladi).
    room_name = models.CharField(max_length=255, blank=True)

    cancelled_by = models.CharField(
        max_length=10, blank=True,
        help_text="Bekor qilgan tomon: patient, doctor, admin",
    )
    cancel_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-start_time"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["doctor", "date"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Konsultatsiya: {self.patient.full_name} → Dr.{self.doctor.user.full_name} ({self.date} {self.start_time}) [{self.status}]"
