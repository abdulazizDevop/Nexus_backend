from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _autofill_doctor_profile, _autofill_patient_profile  # underscore helper (star bermaydi)

class AnalysisType(models.Model):
    """Analiz turi katalogi (Bioximik qon tahlili, Siydik, UZI, ECG…).

    Admin paneldan boshqariladi. `name` va `description` 3 tilli JSON.
    Frontend `?lang=` / `X-Language` ga qarab string oladi.
    """

    class Category(models.TextChoices):
        BLOOD = "blood", "Qon"
        URINE = "urine", "Siydik"
        IMAGING = "imaging", "Tasvir (UZI, Rentgen)"
        CARDIAC = "cardiac", "Yurak (EKG, EXOKG)"
        HORMONES = "hormones", "Gormonlar"
        INFECTION = "infection", "Infeksiya"
        OTHER = "other", "Boshqa"

    name = models.JSONField(default=dict)
    code = models.SlugField(max_length=60, unique=True)
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.OTHER,
        db_index=True,
        help_text="Frontend tabi uchun (Qon / Siydik / Tasvir / ...).",
    )
    icon = models.CharField(max_length=10, blank=True)
    description = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return pick_translation(self.name, "uz") or self.code

class AnalysisIndicator(models.Model):
    """Analiz turi tarkibidagi ko'rsatkichlar (Glyukoza, Kreatinin, ALT, AST…).

    `name` 3 tilli JSON. `unit` universal SI birligi.
    """

    type = models.ForeignKey(
        AnalysisType, on_delete=models.CASCADE, related_name="indicators"
    )
    name = models.JSONField(default=dict)
    code = models.SlugField(max_length=60)
    unit = models.CharField(max_length=30, blank=True)
    normal_min = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    normal_max = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order"]
        unique_together = [("type", "code")]

    def __str__(self):
        return f"{pick_translation(self.name, 'uz') or self.code} ({self.type.code})"

class AnalysisPreparation(models.Model):
    """Tayyorgarlik preset'lari (Och qoringa 8-12 soat, Ertalab, Spirtli yo'q…).

    type=None bo'lsa universal — istalgan analiz turida tanlash mumkin.
    `title` va `description` 3 tilli JSON.
    """

    type = models.ForeignKey(
        AnalysisType,
        on_delete=models.CASCADE,
        related_name="preparations",
        null=True,
        blank=True,
        help_text="None bo'lsa universal.",
    )
    title = models.JSONField(default=dict)
    description = models.JSONField(default=dict, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return pick_translation(self.title, "uz") or f"prep#{self.id}"

class Analysis(models.Model):
    """Bemor analizi.

    Ikki manba (`source`):
      - `doctor_prescribed` — doctor bemorga tayinlaydi, bemor yuklaydi
      - `patient_uploaded`  — bemor o'zi yuklaydi (barcha bog'langan
        doctorlariga avtomatik ko'rinadi)
    """

    class Status(models.TextChoices):
        PRESCRIBED = "prescribed", "Tayinlangan"
        SUBMITTED = "submitted", "Yuborilgan"
        REVIEWED = "reviewed", "Sharhlangan"
        CANCELLED = "cancelled", "Bekor qilingan"

    class Source(models.TextChoices):
        DOCTOR_PRESCRIBED = "doctor_prescribed", "Doctor tayinlagan"
        PATIENT_UPLOADED = "patient_uploaded", "Bemor yuklagan"

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analyses",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="analyses",
        null=True,
        blank=True,
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescribed_analyses",
        help_text=(
            "doctor_prescribed: tayinlagan doctor. "
            "patient_uploaded: birinchi sharh yozgan doctor (avto-tayinlanadi)."
        ),
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescribed_analyses",
    )
    recipients = models.ManyToManyField(
        "doctors.DoctorProfile",
        blank=True,
        related_name="received_analyses",
        help_text=(
            "patient_uploaded uchun: bemorning bog'langan doctorlari (avto-set, "
            "push notification targeting uchun)."
        ),
    )
    type = models.ForeignKey(
        AnalysisType, on_delete=models.PROTECT, related_name="prescriptions"
    )
    indicators = models.ManyToManyField(
        AnalysisIndicator, blank=True, related_name="prescriptions"
    )
    custom_indicators = models.JSONField(
        default=list,
        blank=True,
        help_text="Doctor 'Boshqa' tugmasi orqali qo'shgan qo'shimcha ko'rsatkichlar (erkin matn).",
    )
    preparations = models.ManyToManyField(
        AnalysisPreparation, blank=True, related_name="prescriptions"
    )
    custom_preparations = models.JSONField(
        default=list,
        blank=True,
        help_text="Doctor 'Boshqa' tugmasi orqali qo'shgan qo'shimcha tayyorgarliklar (erkin matn).",
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.DOCTOR_PRESCRIBED,
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        help_text="Bemor qo'ygan nom ('Umumiy qon tahlili'). Bo'sh bo'lsa type.name.",
    )
    recorded_at = models.DateField(
        null=True,
        blank=True,
        help_text="patient_uploaded: analiz topshirilgan sana (laboratoriyada).",
    )
    deadline_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PRESCRIBED
    )
    note = models.TextField(blank=True, help_text="Doctor qo'shimcha izohi")
    verdict = models.TextField(
        blank=True,
        help_text="Doctor xulosasi/sharhi (uzun matn).",
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    cancelled_reason = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    doctor_viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Doctor bemor analizini ko'rgan vaqt (KO'RILDI status uchun).",
    )
    reminder_sent_at = models.DateTimeField(
        null=True, blank=True, help_text="Deadline reminder yuborilgan vaqt (idempotency)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["doctor", "status"]),
            models.Index(fields=["status", "deadline_at"]),
            models.Index(fields=["patient", "source", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        _autofill_patient_profile(self, "patient")
        _autofill_doctor_profile(self, "doctor")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Analysis({self.type}, patient={self.patient_id}, {self.status})"

    def type_name_for(self, user=None) -> str:
        """analysis.type.name JSONField'idan til'ga mos string.

        Push notification matni uchun: recipient'ning preferred til'iga qarab
        AnalysisType.name (JSONField) ni stringga aylantiradi. User tanlanmagan
        bo'lsa default 'uz'.
        """
        lang = "uz"
        if user is not None:
            lang = (
                getattr(getattr(user, "settings", None), "language", None) or "uz"
            )
        return pick_translation(self.type.name, lang)

class AnalysisResult(models.Model):
    """Bemor yuklagan natija (1:1 Analysis). Patient_note + indicator qiymatlari.

    Fayllar `AnalysisFile` orqali (1:N). `file_key` legacy maydon — eski yozuvlar
    uchun saqlanadi, yangi yozuvlar `AnalysisFile`'dan o'qiydi.
    """

    analysis = models.OneToOneField(
        Analysis, on_delete=models.CASCADE, related_name="result"
    )
    file_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="DEPRECATED — yangi multi-file uchun AnalysisFile ishlatiladi.",
    )
    file_mime = models.CharField(max_length=80, blank=True)
    patient_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

class AnalysisFile(models.Model):
    """Analizga ilova qilingan fayl (rasm/PDF). Bir analizda bir nechta fayl bo'la oladi."""

    analysis = models.ForeignKey(
        Analysis, on_delete=models.CASCADE, related_name="files"
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
            models.Index(fields=["analysis", "order"]),
        ]

    def __str__(self):
        return f"File({self.analysis_id}, {self.original_name or self.file_key})"

class AnalysisResultValue(models.Model):
    """Natija ichidagi har bir ko'rsatkich qiymati — trend grafigi uchun alohida qator."""

    result = models.ForeignKey(
        AnalysisResult, on_delete=models.CASCADE, related_name="values"
    )
    indicator = models.ForeignKey(
        AnalysisIndicator, on_delete=models.PROTECT, related_name="result_values"
    )
    value = models.DecimalField(max_digits=12, decimal_places=3)
    is_abnormal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("result", "indicator")]
        indexes = [
            models.Index(fields=["indicator", "-id"]),
        ]

    def save(self, *args, **kwargs):
        if self.indicator_id and self.value is not None:
            mn = self.indicator.normal_min
            mx = self.indicator.normal_max
            self.is_abnormal = bool(
                (mn is not None and self.value < mn)
                or (mx is not None and self.value > mx)
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.indicator.name}={self.value}"
