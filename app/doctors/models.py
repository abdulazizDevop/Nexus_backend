from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from app.users.models import Patient
from core.i18n import pick_translation

User = get_user_model()

# Doctor online deb hisoblanadigan oxirgi WebSocket presence oynasi (sekund).
# Chat consumer `chat:online:{user_id}` flag'ini 90s timeout bilan saqlaydi
# (heartbeat har 60s + 30s bufer) — is_online o'sha flag'ga tayanadi.
ONLINE_PRESENCE_KEY = "chat:online:{user_id}"


class Specialty(models.Model):
    """Mutaxassislik — admin yaratadi, doctor tanlaydi.

    `name` 3 tilli JSON: `{"uz": "Kardiolog", "ru": "Кардиолог", "cyr": "Кардиолог"}`.
    Serializer'da `?lang=` ga qarab mos qiymat qaytariladi (TranslatableFieldsMixin).
    """

    name = models.JSONField(default=dict)
    icon = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name_plural = "specialties"
        # Til bo'yicha tartiblash queryset darajasida `Lower("name__uz")` bilan.

    def __str__(self):
        return pick_translation(self.name, "uz") or "(no name)"

    @property
    def name_uz(self) -> str:
        return pick_translation(self.name, "uz")

    @property
    def name_ru(self) -> str:
        return pick_translation(self.name, "ru")

    @property
    def name_cyr(self) -> str:
        return pick_translation(self.name, "cyr")


class DoctorProfile(models.Model):
    """Doctor profili — user bilan 1:1"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
    )
    specialty = models.ForeignKey(
        Specialty,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="doctors",
        help_text="Asosiy mutaxassislik (`specialties` ro'yxatining birinchisi — orqaga moslik).",
    )
    specialties = models.ManyToManyField(
        Specialty,
        related_name="doctors_multi",
        blank=True,
        help_text="Doctor mutaxassisliklari (bir nechta). `specialty` — birinchisi (asosiy).",
    )
    bio = models.TextField(blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    license_number = models.CharField(max_length=50, blank=True)
    workplace = models.CharField(max_length=255, blank=True)

    is_verified = models.BooleanField(default=False)

    # Doctor o'zi tanlaydi
    accepts_online = models.BooleanField(default=True)
    accepts_offline = models.BooleanField(default=True)

    # Marketplace ("Barcha shifokorlar") ro'yxatida ko'rinsinmi. Doctor opt-out
    # qila oladi — faqat referral (QR/telefon) orqali ishlashni xohlasa. Default
    # ko'rinadi. Ro'yxat qolaversa referral orqali ulanish baribir ochiq.
    marketplace_visible = models.BooleanField(default=True)

    # Individual platforma komissiyasi (%). Bo'sh = global
    # SystemSetting["doctor_commission_percent"] ishlatiladi. Faqat admin belgilaydi.
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Shu doctor uchun individual komissiya (%). Bo'sh bo'lsa global "
        "SystemSetting[doctor_commission_percent] olinadi.",
    )

    # --- Konsultatsiya (bir martalik pullik video-qabul) ---
    # Doctor o'zi yoqadi + narx/davomiylik belgilaydi. Default O'CHIQ — doctor
    # yoqmaguncha bemor marketplace/profilda konsultatsiya ko'rmaydi (§6 backward-compat).
    # Flat ustunlar (accepts_online/marketplace_visible naqshida) — marketplace
    # kartasiga N+1'siz keladi (DoctorProfile qatorining o'zida).
    # MODERATSIYA (tarif kabi): doctor yoqadi/narx qo'yadi → pending → admin
    # tasdiqlaydi → marketplace/booking ochiladi. Narx/davomiylik o'zgarsa qayta pending.
    class ConsultationStatus(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        APPROVED = "approved", "Tasdiqlangan"
        REJECTED = "rejected", "Rad etilgan"

    # O'zgarsa qayta moderatsiyaga qaytaradigan maydonlar (tarif MODERATED_FIELDS kabi).
    CONSULTATION_MODERATED_FIELDS = ["consultation_price", "consultation_duration_min"]

    consultation_enabled = models.BooleanField(default=False)
    consultation_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Bir martalik konsultatsiya narxi (so'm). enabled=True bo'lsa majburiy.",
    )
    consultation_duration_min = models.PositiveIntegerField(
        default=30,
        help_text="Konsultatsiya davomiyligi (daqiqa).",
    )
    consultation_status = models.CharField(
        max_length=10,
        choices=ConsultationStatus.choices,
        default=ConsultationStatus.PENDING,
        help_text="Moderatsiya: faqat approved bo'lsa marketplace'da ko'rinadi/booking ochiladi.",
    )
    consultation_rejection_reason = models.TextField(blank=True)

    # Doctor profilini o'chirish (User bemor sifatida tirik qoladi). Qator
    # SAQLANADI — chunki moliyaviy/audit yozuvlar (DoctorBalance, sotuvlar,
    # payout, review, yakunlangan uchrashuvlar) bunga CASCADE bog'langan va
    # admin statistikasi uchun anonim saqlanishi shart. Operatsion data + PII
    # o'chadi, profil anonimlashtiriladi va katalogdan yashiriladi.
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["specialty", "is_verified"]),
        ]

    def save(self, *args, **kwargs):
        # Konsultatsiya moderatsiyasi (tarif DoctorTariff.save() kabi): TASDIQLANGAN
        # konsultatsiyaning narx/davomiyligi o'zgarsa → qayta moderatsiyaga (pending).
        # Doctor bait-and-switch qilolmaydi; enabled toggle qayta-moderatsiya talab qilmaydi.
        if self.pk:
            old = (
                DoctorProfile.objects.filter(pk=self.pk)
                .only("consultation_status", *self.CONSULTATION_MODERATED_FIELDS)
                .first()
            )
            if old and old.consultation_status == self.ConsultationStatus.APPROVED:
                changed = any(
                    getattr(old, f) != getattr(self, f)
                    for f in self.CONSULTATION_MODERATED_FIELDS
                )
                if changed:
                    self.consultation_status = self.ConsultationStatus.PENDING
                    self.consultation_rejection_reason = ""
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Dr. {self.user.full_name}"

    # --- Avtomatik hisoblanadigan fieldlar ---

    @property
    def rating(self):
        """O'rtacha reyting — reviewlardan hisoblanadi.

        View .annotate(_rating_avg=Avg("reviews__rating")) bersa — N+1'siz.
        """
        if hasattr(self, "_rating_avg"):
            return round(self._rating_avg, 2) if self._rating_avg else 0
        from app.feedbacks.models import Review

        avg = Review.objects.filter(doctor=self).aggregate(avg=models.Avg("rating"))[
            "avg"
        ]
        return round(avg, 2) if avg else 0

    @property
    def total_reviews(self):
        if hasattr(self, "_total_reviews"):
            return self._total_reviews
        from app.feedbacks.models import Review

        return Review.objects.filter(doctor=self).count()

    @property
    def total_patients(self):
        """Doctor ga birikkan bemorlar soni (DoctorPatient ACCEPTED + referral)"""
        return len(patient_ids_for_doctor(self))

    @property
    def is_online(self):
        """WebSocket presence asosida online holati.

        `last_login` bu auth oqimida (OTP+JWT) hech qachon yangilanmaydi, shuning
        uchun unga tayanmaymiz. Chat consumer ulanish/heartbeat'da
        `chat:online:{user_id}` cache flag'ini 90s timeout bilan saqlaydi —
        doctor real-time ulangan bo'lsa True qaytadi.
        """
        return bool(cache.get(ONLINE_PRESENCE_KEY.format(user_id=self.user_id)))


class DoctorPatient(models.Model):
    """Doctor-Patient bog'lanishi.

    Flow:
      1. Bir tomon so'rov yuboradi → status=pending, requested_by=o'sha tomon
      2. Ikkinchi tomon accept/decline qiladi
      3. accept → status=accepted (bog'lanish aktiv)
         decline → status=declined (bog'lanish yo'q, lekin yozuv saqlanadi)

    Qoida: accepted yozuvlar UI'da ko'rinadi, pending/declined alohida ro'yxatda.
    """

    class AddedBy(models.TextChoices):
        DOCTOR = "doctor", "Doctor"
        PATIENT = "patient", "Patient"

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        ACCEPTED = "accepted", "Qabul qilingan"
        DECLINED = "declined", "Rad etilgan"

    doctor = models.ForeignKey(
        "DoctorProfile",
        on_delete=models.CASCADE,
        related_name="doctor_patients",
    )
    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="patient_doctors",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="doctor_relationships",
        null=True,
        blank=True,
    )
    added_by = models.CharField(max_length=10, choices=AddedBy.choices)
    requested_by = models.CharField(
        max_length=10,
        choices=AddedBy.choices,
        default=AddedBy.PATIENT,
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.ACCEPTED,
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["doctor", "patient"]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doctor", "patient"]),
            models.Index(fields=["status", "requested_by"]),
        ]

    def save(self, *args, **kwargs):
        if self.patient_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.patient_id)
            self.patient_profile = patient_profile
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Dr. {self.doctor.user.full_name} — {self.patient.full_name}"


class DoctorCertificate(models.Model):
    """Sertifikatlar va mukofotlar"""

    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="certificates",
    )
    title = models.CharField(max_length=255)
    issuer = models.CharField(max_length=255, blank=True)
    year = models.PositiveIntegerField(null=True, blank=True)
    image = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="DO Spaces key (masalan: 'certificates/5/abc123.jpg')",
    )

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return self.title


class Slot(models.Model):
    """Doctor jadvalining alohida slot qatori.

    Slot — virtual emas, har biri DB qatori. Doctor `/me/slots/sync/` orqali
    aniq sanada yarata oladi, o'zgartira oladi yoki o'chira oladi. Patient
    booking flow `free → booked` tranzitsiyasini atomic tarzda qiladi.
    """

    class Status(models.TextChoices):
        FREE = "free", "Bo'sh"
        BOOKED = "booked", "Bron qilingan"
        BLOCKED = "blocked", "Yopilgan"

    doctor = models.ForeignKey(
        DoctorProfile,
        on_delete=models.CASCADE,
        related_name="slots",
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.FREE,
    )
    appointment = models.OneToOneField(
        "meetings.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slot",
    )
    # Konsultatsiya booking (bir Slot pool appointment + consultation'ni qamraydi
    # → bir slotni ikki oqim bandlay olmaydi, status=BOOKED + UniqueConstraint).
    consultation = models.OneToOneField(
        "meetings.Consultation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slot",
    )
    reason = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "date", "start_time"],
                name="uniq_slot_doctor_date_start",
            ),
        ]
        indexes = [
            models.Index(fields=["doctor", "date"]),
            models.Index(fields=["doctor", "date", "status"]),
        ]

    def __str__(self):
        return f"{self.date} {self.start_time}-{self.end_time} ({self.status})"


# --- Bemor-id helperlari (referral + DoctorPatient ACCEPTED union) ---


def patient_ids_by_doctor(profiles) -> dict:
    """Bir nechta doctor uchun bemor user-id'lar to'plamini bitta-ikkita agregat
    so'rovda hisoblaydi.

    `profiles` — DoctorProfile obyektlari ro'yxati. Qaytaradi:
        {doctor_profile_id: set(patient_user_id, ...)}
    Har doctor uchun: referral orqali birikkanlar (User.referred_by) ∪
    DoctorPatient ACCEPTED bemorlar. List view'lardagi N+1 oldini olish uchun.
    """
    profiles = list(profiles)
    if not profiles:
        return {}

    user_ids = [p.user_id for p in profiles]
    profile_ids = [p.id for p in profiles]
    user_to_profiles: dict[int, list] = {}
    for p in profiles:
        user_to_profiles.setdefault(p.user_id, []).append(p.id)

    result: dict[int, set] = {p.id: set() for p in profiles}

    for ref_id, by_user_id in User.objects.filter(
        referred_by_id__in=user_ids
    ).values_list("id", "referred_by_id"):
        for pid in user_to_profiles.get(by_user_id, []):
            result[pid].add(ref_id)

    for patient_id, doctor_id in DoctorPatient.objects.filter(
        doctor_id__in=profile_ids,
        status=DoctorPatient.Status.ACCEPTED,
    ).values_list("patient_id", "doctor_id"):
        if doctor_id in result:
            result[doctor_id].add(patient_id)

    return result


def patient_ids_for_doctor(profile) -> set:
    """Bitta doctor uchun bemor user-id'lar to'plami (batch helper ustidagi o'ram)."""
    if not profile:
        return set()
    return patient_ids_by_doctor([profile]).get(profile.id, set())
