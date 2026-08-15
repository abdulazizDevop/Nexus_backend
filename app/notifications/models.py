from django.conf import settings
from django.db import models
from django.utils import timezone


class DeviceToken(models.Model):
    """Foydalanuvchi qurilmasining push tokeni.

    Bitta iOS qurilmada 2 ta token bo'ladi:
      - FCM token (chat, eslatma — oddiy push)
      - VoIP APNS token (faqat incoming call, PushKit orqali — CallKit ringtone)

    Token unique — agar boshqa user bilan bog'langan bo'lsa, yangi user'ga o'tkaziladi.
    """

    class Platform(models.TextChoices):
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"
        WEB = "web", "Web"

    class TokenType(models.TextChoices):
        FCM = "fcm", "FCM (oddiy push)"
        VOIP_APNS = "voip_apns", "iOS VoIP PushKit"

    class Environment(models.TextChoices):
        PRODUCTION = "production", "Production (App Store / TestFlight)"
        DEVELOPMENT = "development", "Development (Xcode debug build)"

    class AppScope(models.TextChoices):
        PATIENT = "patient", "Patient app (com.mediik.patient)"
        DOCTOR = "doctor", "Doctor app (com.mediik.doctor)"
        ADMIN = "admin", "Admin panel (web)"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
    )
    token = models.CharField(max_length=512, unique=True)
    # Phase 3+: jismoniy device identifikatori (iOS identifierForVendor,
    # Android ANDROID_ID, yoki barqaror per-device UUID). Bir xil telefonda
    # turgan Patient va Doctor app — BIR XIL device_id, lekin alohida `token`.
    # Self-call blokrovkasi va per-device logika uchun.
    device_id = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
        help_text="iOS identifierForVendor yoki Android device ID",
    )
    platform = models.CharField(max_length=10, choices=Platform.choices)
    # Phase 3+: qaysi app shu tokenni registratsiya qilgan. Mediik patient va
    # doctor app'lar alohida bundle ID'larga ega — push notification'larni
    # to'g'ri app'ga yo'naltirish uchun (yangi qabul push'i — faqat doctor app).
    app_scope = models.CharField(
        max_length=10,
        choices=AppScope.choices,
        null=True,
        blank=True,
        help_text="Qaysi app tokenni registratsiya qilgan (patient/doctor/admin).",
    )
    token_type = models.CharField(
        max_length=12,
        choices=TokenType.choices,
        default=TokenType.FCM,
        help_text="FCM — oddiy push. voip_apns — iOS PushKit (incoming call).",
    )
    environment = models.CharField(
        max_length=12,
        choices=Environment.choices,
        default=Environment.PRODUCTION,
        help_text=(
            "APNS endpoint tanlash uchun (faqat voip_apns token uchun ahamiyatli). "
            "Xcode debug build'dan kelgan token — 'development', TestFlight va "
            "App Store build — 'production'."
        ),
    )
    device_name = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_used_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "token_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} — {self.platform}/{self.token_type} ({self.token[:12]}...)"


class Notification(models.Model):
    """Foydalanuvchining ichki xabarnoma yozuvi.

    Push yuborilganda shu yozuv yaratiladi va ilovadagi "Bildirishnomalar" sahifasida
    ro'yxat shaklida ko'rinadi. `data` JSON — frontend deeplink ochish uchun
    qo'shimcha kontekst (appointment_id, treatment_id, room_id va h.k.).
    """

    class Type(models.TextChoices):
        TREATMENT_REMINDER = "treatment_reminder", "Muolaja eslatmasi"
        APPOINTMENT_CREATED = "appointment_created", "Yangi qabul so'rovi"
        APPOINTMENT_APPROVED = "appointment_approved", "Qabul tasdiqlandi"
        APPOINTMENT_REJECTED = "appointment_rejected", "Qabul rad etildi"
        REVIEW_REMINDER = "review_reminder", "Review qoldirish eslatmasi"
        NEW_REVIEW = "new_review", "Yangi review keldi"
        TARIFF_APPROVED = "tariff_approved", "Tarif tasdiqlandi"
        TARIFF_REJECTED = "tariff_rejected", "Tarif rad etildi"
        PAYOUT_COMPLETED = "payout_completed", "Pul yechish bajarildi"
        PAYOUT_REJECTED = "payout_rejected", "Pul yechish rad etildi"
        OFFLINE_PAYMENT_REQUEST = "offline_payment_request", "Offline to'lov tasdiqlash so'rovi"
        OFFLINE_PAYMENT_CONFIRMED = "offline_payment_confirmed", "Offline to'lov tasdiqlandi"
        OFFLINE_PAYMENT_REJECTED = "offline_payment_rejected", "Offline to'lov rad etildi"
        CHAT_MESSAGE = "chat_message", "Yangi xabar"
        SUPPORT_MESSAGE = "support_message", "Qo'llab-quvvatlash javobi"
        CALL_MISSED = "call_missed", "Javobsiz qo'ng'iroq"
        CONNECTION_REQUEST = "connection_request", "Bog'lanish so'rovi"
        CONNECTION_ACCEPTED = "connection_accepted", "Bog'lanish qabul qilindi"
        CONNECTION_DECLINED = "connection_declined", "Bog'lanish rad etildi"
        ADMIN_BROADCAST = "admin_broadcast", "Tizim e'loni"
        SYSTEM = "system", "Tizim xabari"
        DAILY_AI_REPORT = "daily_ai_report", "Kunlik AI hisobot (jiddiy signal)"
        FAMILY_INVITE = "family_invite", "Oila a'zosi taklifi"
        FAMILY_ACCEPTED = "family_accepted", "Oila taklifi qabul qilindi"
        FAMILY_DECLINED = "family_declined", "Oila taklifi rad etildi"
        TRACKING_ALERT = "tracking_alert", "AI kuzatuv ogohlantirishi"
        CALORIE_LIMIT = "calorie_limit", "Kaloriya normasi yangilandi"
        CONSULTATION_BOOKED = "consultation_booked", "Yangi konsultatsiya (to'landi)"
        CONSULTATION_CONFIRMED = "consultation_confirmed", "Konsultatsiya tasdiqlandi"
        CONSULTATION_CANCELLED = "consultation_cancelled", "Konsultatsiya bekor qilindi"
        CONSULTATION_REMINDER = "consultation_reminder", "Konsultatsiya eslatmasi"
        CONSULTATION_APPROVED = "consultation_approved", "Konsultatsiya moderatsiyadan o'tdi"
        CONSULTATION_REJECTED = "consultation_rejected", "Konsultatsiya rad etildi"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(
        max_length=32, choices=Type.choices, default=Type.SYSTEM
    )
    app_scope = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        db_index=True,
        help_text="'patient' | 'doctor' | 'admin' — qaysi ilovada ko'rinadi. "
        "null = barcha ilovalar (tizim/broadcast/legacy).",
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} — {self.type}: {self.title[:32]}"

    def mark_read(self):
        if self.is_read:
            return
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])
