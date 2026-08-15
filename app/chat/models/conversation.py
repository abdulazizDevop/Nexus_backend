from .common import *  # noqa: F401,F403


class ChatRoom(models.Model):
    """Chat xonasi — consultation (doctor-patient) yoki support (user-admin).

    Maydonlar:
      - participants — kim qatnashayapti (User-darajasida)
      - patient — Patient profile (CONSULTATION room'lar uchun)
      - doctor — DoctorProfile (CONSULTATION room'lar uchun)

    Bir user ham bemor, ham doctor bo'lishi mumkin. Shu sababli chat xonasi
    `(patient_id, doctor_id)` orqali aniqlanadi — User A (patient) ↔ User B
    (doctor) va User A (doctor) ↔ User B (patient) — ikki alohida xona.
    """

    class RoomType(models.TextChoices):
        CONSULTATION = "consultation", "Konsultatsiya"
        SUPPORT = "support", "Qo'llab-quvvatlash"

    room_type = models.CharField(
        max_length=15, choices=RoomType.choices, default=RoomType.CONSULTATION
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="chat_rooms",
    )
    # Yangi (nullable) — CONSULTATION room'lar uchun aniq Patient va Doctor
    patient = models.ForeignKey(
        "users.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )
    doctor = models.ForeignKey(
        "doctors.DoctorProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chat_rooms",
    )
    is_active = models.BooleanField(default=True)
    # Marketplace privacy: doctor shu vaqtdan OLDINGI xabarlarni ko'rmaydi.
    # Bemor marketplace'da connection'siz AI bilan suhbatlashadi (bu doctor'ga
    # ko'rinmasligi kerak); tarif xaridi = ACCEPTED connection + shu maydon
    # xarid vaqtiga o'rnatiladi → doctor faqat xariddan keyingi "toza chat"ni
    # ko'radi. Bemor har doim to'liq tarixni ko'radi. Null = hech narsa yashirilmaydi
    # (referral/oddiy room'lar). Faqat DOCTOR viewer'ga ta'sir qiladi.
    doctor_visible_from = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["patient", "doctor"]),
        ]
        constraints = [
            # Bir Patient + Doctor juftligi uchun bitta consultation xona.
            # Race condition'ni oldini oladi (ikki bir vaqtda kelgan request).
            # Faqat ikkalasi non-null bo'lganida — partial unique (PostgreSQL).
            models.UniqueConstraint(
                fields=["patient", "doctor"],
                condition=models.Q(
                    patient__isnull=False, doctor__isnull=False
                ),
                name="unique_consultation_room_per_patient_doctor",
            ),
        ]

    def __str__(self):
        names = ", ".join(self.participants.values_list("full_name", flat=True)[:2])
        return f"Chat #{self.id}: {names}"

    @classmethod
    def get_or_create_for_users(cls, user1, user2):
        """Ikki user uchun mavjud unikal chatni qaytaradi yoki yangi yaratadi.

        Backwards compatible: hozircha User-darajasida ishlaydi. Yangi kod
        `get_or_create_consultation(patient, doctor)` ishlatsin — aniq Patient/
        Doctor identitilari bilan.
        """
        existing = (
            cls.objects.filter(participants=user1).filter(participants=user2).first()
        )

        if existing:
            return existing, False

        room = cls.objects.create()
        room.participants.add(user1, user2)
        return room, True

    @classmethod
    def get_or_create_consultation(cls, patient, doctor_profile):
        """Patient va Doctor ID bo'yicha unikal consultation xonani qaytaradi.

        Bir user bir vaqtda ham patient, ham doctor bo'lishi mumkin, lekin
        xona alohida bo'ladi. Race-safe: transaction.atomic + UniqueConstraint
        orqali bir vaqtda kelgan ikki request'da ham bitta xona qaytariladi.
        """
        from django.db import IntegrityError, transaction

        # Tez yo'l — mavjud xonani topish (lock'siz)
        existing = cls.objects.filter(
            patient=patient,
            doctor=doctor_profile,
            room_type=cls.RoomType.CONSULTATION,
        ).first()
        if existing:
            return existing, False

        # Yangi xona yaratish — race condition uchun atomic
        try:
            with transaction.atomic():
                room = cls.objects.create(
                    room_type=cls.RoomType.CONSULTATION,
                    patient=patient,
                    doctor=doctor_profile,
                )
                room.participants.add(patient.user, doctor_profile.user)
                return room, True
        except IntegrityError:
            # UniqueConstraint ishladi — boshqa request bizdan oldin yaratdi
            existing = cls.objects.filter(
                patient=patient,
                doctor=doctor_profile,
                room_type=cls.RoomType.CONSULTATION,
            ).first()
            if existing:
                return existing, False
            raise  # boshqa IntegrityError'ni qayta ko'taramiz


class Message(models.Model):
    """Chat xabari — text, media, system"""

    class MessageType(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        FILE = "file", "File"
        SYSTEM = "system", "System"

    class SenderScope(models.TextChoices):
        PATIENT = "patient", "Patient"
        DOCTOR = "doctor", "Doctor"
        ADMIN = "admin", "Admin"

    class AudioStatus(models.TextChoices):
        PENDING = "pending", "Transcode kutilmoqda"
        READY = "ready", "Tayyor"
        FAILED = "failed", "Xato"

    class TranscriptStatus(models.TextChoices):
        PENDING = "pending", "Transkripsiya qilinmoqda"
        READY = "ready", "Tayyor"
        FAILED = "failed", "Xato"

    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    # Yuborish paytida user qaysi rol-konteksida edi (JWT scope'dan).
    # Eski xabarlarda null — view'da qayta hisoblanmaydi (audit safe).
    sender_scope = models.CharField(
        max_length=10,
        choices=SenderScope.choices,
        null=True,
        blank=True,
        help_text="Yuborish paytida user'ning JWT scope'i.",
    )
    message_type = models.CharField(
        max_length=10,
        choices=MessageType.choices,
        default=MessageType.TEXT,
    )
    content = models.TextField(blank=True)
    # Fayl DO Spaces da — file_key = "chat/1/2026/04/uuid_photo.jpg"
    file_key = models.CharField(max_length=500, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    file_type = models.CharField(max_length=100, blank=True)
    # Faqat AUDIO xabarlarda — web webm/opus → m4a asinxron transcode holati.
    # null = audio bo'lmagan xabar yoki transcode kerak emas (mobil m4a darhol ready).
    #   pending → transcode queue'ga qo'yildi (web webm/opus/ogg)
    #   ready   → transcode tugadi yoki kerak emas edi (mobil mos format)
    #   failed  → transcode permanent xato (eski webm o'zi qoladi, fallback)
    audio_status = models.CharField(
        max_length=10,
        choices=AudioStatus.choices,
        null=True,
        blank=True,
        help_text="Ovozli xabar transcode holati (web webm→m4a). Audio bo'lmasa null.",
    )
    # On-demand STT (faqat bemor ovozi, doctor so'raganda). Transkript saqlanadi —
    # qayta so'rovda Gemini chaqirilmaydi.
    transcript = models.TextField(
        blank=True, help_text="Ovozli xabar STT transkripti (Gemini, on-demand)."
    )
    transcript_status = models.CharField(
        max_length=10,
        choices=TranscriptStatus.choices,
        null=True,
        blank=True,
        help_text="STT holati. null = hali so'ralmagan.",
    )

    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    # AI gatekeeper: tarifsiz bemorga avto-javob (sender texnik jihatdan doctor,
    # lekin bu flag bilan frontend "AI yordamchi" deb ko'rsatadi).
    is_ai = models.BooleanField(
        default=False,
        help_text="AI yordamchi yuborgan avto-javob (sender doctor, lekin AI).",
    )
    # default + db_index — mobile send order'da saqlash uchun consumer
    # `created_at` ni override qiladi (audio/file upload tartibsiz tugaydi).
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["room", "created_at"]),
            models.Index(fields=["room", "is_read"]),
            models.Index(fields=["sender", "created_at"]),
        ]

    def __str__(self):
        return f"{self.sender.full_name}: {self.content[:50] or self.file_name}"

    @classmethod
    def create_system(cls, room, content, *, sender, scope=None, **extra):
        """System xabar yaratish (bitta manba).

        sender_scope va message_type=SYSTEM ni qo'lda berishni unutib qo'yish
        nomuvofiqligini oldini oladi. `room` ChatRoom obyekti yoki room_id
        bo'lishi mumkin (room_id=... orqali).
        """
        kwargs = dict(
            sender=sender,
            sender_scope=scope,
            message_type=cls.MessageType.SYSTEM,
            content=content,
        )
        kwargs.update(extra)
        if isinstance(room, int):
            kwargs["room_id"] = room
        else:
            kwargs["room"] = room
        return cls.objects.create(**kwargs)


class CallSession(models.Model):
    """Chat ichida video/audio qo'ng'iroq sessiyasi (Telegram-style)."""

    class CallType(models.TextChoices):
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"

    class Status(models.TextChoices):
        RINGING = "ringing", "Jiringlamoqda"
        ACTIVE = "active", "Faol"
        COMPLETED = "completed", "Tugallangan"
        MISSED = "missed", "Javobsiz"
        REJECTED = "rejected", "Rad etilgan"
        CANCELLED = "cancelled", "Bekor qilingan"

    class ParticipantScope(models.TextChoices):
        PATIENT = "patient", "Patient"
        DOCTOR = "doctor", "Doctor"
        ADMIN = "admin", "Admin"

    room = models.ForeignKey(
        ChatRoom, on_delete=models.CASCADE, related_name="call_sessions"
    )
    caller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="outgoing_calls",
    )
    callee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="incoming_calls",
    )
    # Qo'ng'iroq paytida har ishtirokchining rol-konteksti.
    caller_scope = models.CharField(
        max_length=10,
        choices=ParticipantScope.choices,
        null=True,
        blank=True,
        help_text="Caller JWT scope'i (qo'ng'iroq qilgandagi rol)",
    )
    callee_scope = models.CharField(
        max_length=10,
        choices=ParticipantScope.choices,
        null=True,
        blank=True,
        help_text="Callee'ning kutilgan rol-konteksti (xona turidan kelib chiqib).",
    )
    call_type = models.CharField(max_length=10, choices=CallType.choices)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.RINGING
    )
    room_name = models.CharField(max_length=100)
    started_at = models.DateTimeField(null=True, blank=True)
    ringing_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Callee qurilmasi incoming UI ko'rsatgani (delivery ack) vaqti",
    )
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.PositiveIntegerField(default=0, help_text="Soniyalarda")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["room", "-created_at"]),
            models.Index(fields=["callee", "status"]),
        ]

    def __str__(self):
        return f"Call #{self.id}: {self.caller} → {self.callee} ({self.get_status_display()})"

    @property
    def duration_display(self):
        if self.duration <= 0:
            return "0:00"
        minutes, seconds = divmod(self.duration, 60)
        return f"{minutes}:{seconds:02d}"

    # --- System message matnlari (bitta manba, drift oldini olish) ---
    # Emoji + matn shablonlari ilgari views/consumer/tasks da 4 joyda
    # takrorlanardi — biri o'zgarsa boshqasi eskirib qolardi.

    @property
    def call_type_label(self) -> str:
        """'Video' yoki 'Audio' (bosh harf bilan)."""
        return "Video" if self.call_type == self.CallType.VIDEO else "Audio"

    def system_message_missed(self) -> str:
        return f"📞 Javobsiz {self.call_type_label.lower()} qo'ng'iroq"

    def system_message_rejected(self) -> str:
        return f"📞 Rad etilgan {self.call_type_label.lower()} qo'ng'iroq"

    def system_message_finished(self) -> str:
        """COMPLETED → davomiylik bilan, aks holda 'Bekor qilingan'."""
        if self.status == self.Status.COMPLETED:
            return f"📞 {self.call_type_label} qo'ng'iroq — {self.duration_display}"
        return f"📞 Bekor qilingan {self.call_type_label.lower()} qo'ng'iroq"
