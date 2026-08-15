from .common import *  # noqa: F401,F403


def _parse_time_str(raw):
    """"HH:MM" yoki "HH:MM:SS" (yoki time obyekti) → time. Noto'g'ri bo'lsa None."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, dt_time):
        return raw
    s = str(raw)
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


class Treatment(models.Model):
    """Muolaja — dori, mashq, parhez, suv ichish, uyqu"""

    class Type(models.TextChoices):
        MEDICATION = "medication", "Dori"
        EXERCISE = "exercise", "Mashq"
        DIET = "diet", "Parhez"
        WATER = "water", "Suv ichish"
        SLEEP = "sleep", "Uyqu"

    class Status(models.TextChoices):
        ACTIVE = "active", "Faol"
        PAUSED = "paused", "To'xtatilgan"
        COMPLETED = "completed", "Tugallangan"

    class Repeat(models.TextChoices):
        DAILY = "daily", "Har kuni"
        EVERY_OTHER_DAY = "every_other_day", "Har ikki kuni"
        THREE_TIMES_WEEK = "three_times_week", "Har uch kuni"
        WEEKLY = "weekly", "Haftalik"
        BIWEEKLY = "biweekly", "Har ikki haftada"
        MONTHLY = "monthly", "Oylik"
        CUSTOM = "custom", "Maxsus"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="treatments",
    )
    patient_profile = models.ForeignKey(
        "users.Patient",
        on_delete=models.CASCADE,
        related_name="treatments",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescribed_treatments",
        help_text="Doctor yozgan bo'lsa — doctor user, patient o'zi qo'shgan bo'lsa null",
    )
    doctor_profile = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescribed_treatments",
        help_text="Treatment'ni yozgan doctor (patient self-add bo'lsa null).",
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    title = models.CharField(max_length=255)
    dosage = models.CharField(max_length=100, blank=True)
    duration = models.CharField(max_length=100, blank=True)
    time = models.TimeField(
        null=True, blank=True,
        help_text="Birinchi qabul vaqti. interval_hours bo'lsa boshlanish vaqti.",
    )
    end_time = models.TimeField(
        null=True, blank=True,
        help_text="Oxirgi qabul vaqti. interval_hours bilan ishlatiladi.",
    )
    interval_hours = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Har necha soatda (masalan 2 = har 2 soatda). time dan end_time gacha.",
    )
    repeat = models.CharField(
        max_length=20, choices=Repeat.choices, default=Repeat.DAILY
    )
    custom_days = models.CharField(
        max_length=20, blank=True,
        help_text="repeat=custom bo'lsa hafta kunlari: '1,3,5' (1=Du, 7=Ya)",
    )
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Muolaja tugash sanasi. Null = cheksiz.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Eslatmalar (ixtiyoriy) — qo'shimcha ko'rsatmalar.",
    )
    # --- "Kerak bo'lganda" (PRN) dori rejimi ---
    is_as_needed = models.BooleanField(
        default=False,
        help_text="True = ehtiyoj bo'lganda ichiladi (jadval/eslatma yo'q).",
    )
    as_needed_reason = models.TextField(
        blank=True,
        help_text=(
            "Qaysi holatda ichish (masalan 'Harorat 38° dan oshganda'). "
            "Faqat is_as_needed=True da mazmunli."
        ),
    )
    max_per_day = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Xavfsizlik chegarasi: kuniga eng ko'pi bilan necha marta.",
    )
    min_interval_hours = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Xavfsizlik chegarasi: qabullar orasida kamida soat.",
    )
    # Kun ichidagi ANIQ qabul vaqtlari: ["08:00:00", "12:00:00", "19:00:00"].
    # Berilsa — multi-slot manbai (yo'qotuvchi interval_hours siqishni almashtiradi).
    # Bo'sh bo'lsa — time/interval_hours/end_time'ga fallback (eski yozuvlar).
    times = models.JSONField(
        default=list, blank=True,
        help_text='Aniq qabul vaqtlari ro\'yxati: ["08:00:00", ...]. Multi-slot uchun.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["time"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "time"]),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and not self.patient_profile_id:
            patient_profile, _ = Patient.objects.get_or_create(user_id=self.user_id)
            self.patient_profile = patient_profile
        if self.created_by_id and not self.doctor_profile_id:
            dp = DoctorProfile.objects.filter(user_id=self.created_by_id).first()
            if dp:
                self.doctor_profile = dp
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_type_display()}: {self.title}"

    @property
    def is_active(self):
        """Status active va end_date o'tmagan bo'lsa True"""
        if self.status != self.Status.ACTIVE:
            return False
        if self.end_date and self.end_date < timezone.localdate():
            return False
        return True

    def is_scheduled_today(self):
        """Bugun bajarilishi kerakmi (aktiv + jadval parity)?"""
        return self.is_active and self._scheduled_on(timezone.localdate())

    def _scheduled_on(self, date):
        """`date` kuni jadval bo'yicha qabul bormi (repeat/custom_days parity).

        is_active'dan MUSTAQIL — tarixiy kunlar uchun ham ishlaydi (stats maxraji).
        created_at'dan oldin yoki end_date'dan keyin bo'lsa — False.
        """
        # LOCAL sana — UTC .date() yarim tun atrofida bir kun siljitib,
        # every_other_day/weekly parity'ni buzadi.
        ref = timezone.localtime(self.created_at).date() if self.created_at else date
        if date < ref:
            return False
        if self.end_date and date > self.end_date:
            return False
        weekday = date.isoweekday()  # 1=Du, 7=Ya
        R = self.Repeat
        if self.repeat == R.DAILY:
            return True
        if self.repeat == R.EVERY_OTHER_DAY:
            return (date - ref).days % 2 == 0
        if self.repeat == R.THREE_TIMES_WEEK:
            return weekday in (1, 3, 5)  # Du, Chor, Ju
        if self.repeat == R.WEEKLY:
            return weekday == ref.isoweekday()
        if self.repeat == R.BIWEEKLY:
            return (date - ref).days % 14 == 0
        if self.repeat == R.MONTHLY:
            return date.day == ref.day
        if self.repeat == R.CUSTOM:
            if not self.custom_days:
                return False
            days = [int(d) for d in self.custom_days.split(",") if d.strip().isdigit()]
            return weekday in days
        return False

    def slots_per_day(self):
        """Kuniga rejalashtirilgan doza (slot) soni — stats maxraji uchun.

        PRN/uyqu → 0. `times` bo'lsa uning uzunligi; bitta `time` → 1;
        VAQTSIZ rejali dori ("payt emas") ham kuniga 1 marta belgilanadigan
        ish — 1 (aks holda maxrajga kirmay, completion >100% chiqadi).
        """
        if self.is_as_needed or self.type == self.Type.SLEEP:
            return 0
        if self.times:
            parsed = sum(1 for t in self.times if _parse_time_str(t))
            if parsed:
                return parsed
        return 1

    def get_scheduled_times(self):
        """Bugungi barcha qabul vaqtlarini qaytaradi.

        `times` (aniq ro'yxat) bo'lsa — o'sha (yo'qotuvchi siqishsiz). Aks holda
        interval_hours bo'lsa: time dan end_time gacha har X soatda. Bo'lmasa: faqat time.
        """
        if self.times:
            parsed = [t for t in (_parse_time_str(x) for x in self.times) if t]
            if parsed:
                return sorted(parsed)

        if not self.time:
            return []

        if not (self.interval_hours and self.end_time):
            return [self.time]

        times = []
        current = self.time
        while current <= self.end_time:
            times.append(current)
            total_minutes = current.hour * 60 + current.minute + self.interval_hours * 60
            if total_minutes >= 24 * 60:
                break
            current = dt_time(total_minutes // 60, total_minutes % 60)
        return times


class TreatmentLog(models.Model):
    """Muolaja bajarildi/bajarilmadi logi"""

    class Status(models.TextChoices):
        COMPLETED = "completed", "Bajarildi"
        SKIPPED = "skipped", "O'tkazib yuborildi"

    treatment = models.ForeignKey(
        Treatment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    # Treatment o'chsa ham tarix qolishi uchun denormalized maydonlar
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="treatment_logs",
        null=True,
        blank=True,
    )
    treatment_title = models.CharField(max_length=255, blank=True)
    treatment_type = models.CharField(max_length=20, blank=True)
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Rejali dori uchun bu log QAYSI slotga (vaqtga) tegishli — slotning aniq
    # wall-clock vaqti (offset bilan). Per-slot mustaqil belgilash uchun.
    # PRN dori → null (taken_at bilan kalitlanadi, slot yo'q).
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-date"]
        # PRN (is_as_needed) dori kuniga bir necha marta loglanadi — shuning uchun
        # "treatment+date" unique constraint OLIB TASHLANDI. Rejali dori esa
        # per-slot idempotent: (treatment, scheduled_for) partial unique (faqat
        # scheduled_for not null) — har slot bittadan, PRN (null) multi-log buzilmaydi.
        indexes = [
            models.Index(fields=["treatment", "date", "status"]),
            models.Index(fields=["user", "date", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["treatment", "scheduled_for"],
                condition=models.Q(scheduled_for__isnull=False),
                name="uniq_treatment_scheduled_slot",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.treatment_id:
            if not self.user_id:
                self.user_id = self.treatment.user_id
            if not self.treatment_title:
                self.treatment_title = self.treatment.title
            if not self.treatment_type:
                self.treatment_type = self.treatment.type
        super().save(*args, **kwargs)

    def __str__(self):
        title = self.treatment_title or (self.treatment.title if self.treatment else "—")
        return f"{title} - {self.date} - {self.get_status_display()}"
