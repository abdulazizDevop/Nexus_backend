import random
import string
import time

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.utils import timezone

# OTP resend rate limit (Eskiz bill DoS + Telegram spam himoyasi).
# Per phone (IP rotation himoya bermaydi):
#   - 60 soniya cooldown ikki ketma-ket OTP send orasida
#   - sutkalik 10 ta OTP limiti
_OTP_COOLDOWN_SEC = 60
_OTP_DAILY_LIMIT = 10
_OTP_DAILY_TTL = 86400

# Bypass-raqamlar (store review akkauntlari) shu kod bilan kiradi. settings'da
# BYPASS_OTP_CODE bo'lsa undan, aks holda shu default'dan foydalaniladi —
# kod bir joyda, models va view bir xil qiymatga tayanadi.
BYPASS_OTP_CODE = getattr(settings, "BYPASS_OTP_CODE", "0000")


class OTPCode(models.Model):
    PURPOSE_CHOICES = [
        ("register", "Register"),
        ("login", "Login"),
    ]

    phone = models.CharField(max_length=15)
    code = models.CharField(max_length=10)
    purpose = models.CharField(max_length=10, choices=PURPOSE_CHOICES)
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=10, blank=True)
    # Doctor registratsiyasida bot referral code'ni so'raydi va validate qiladi.
    # /auth/auth/verify/ user yaratishda shu yerdan foydalanadi (frontend'dan
    # qayta yuborish shart emas).
    referral_code = models.CharField(max_length=20, blank=True)
    # Bot inline button orqali tanlanadi (male/female), keyin user yaratganda
    # User.sex ga ko'chiriladi. Frontend (SMS register) o'z field'iga qo'yadi.
    sex = models.CharField(max_length=10, blank=True)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True)
    is_used = models.BooleanField(default=False)
    # Brute-force counter: har noto'g'ri urinishda oshadi, OTP_MAX_ATTEMPTS ga
    # yetganda kod bekor (is_used=True) qilinadi.
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OTP {self.code} for {self.phone} ({self.purpose})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    @classmethod
    def check_send_cooldown(cls, phone: str):
        """OTP yuborishdan oldin chastotani tekshirish.

        Return: (ok, retry_after_seconds, reason).
            ok=True       — yuborish mumkin
            ok=False      — chastota chegarasi oshib ketgan
            retry_after   — kelgusi urinish uchun necha soniya
            reason        — 'cooldown' (60s) yoki 'daily_limit' (24h)

        DEBUG=True (lokal/dev) da hech qanday chegara yo'q — test qulayligi
        uchun. Eskiz cost va Telegram spam faqat prod'da xavf.
        """
        if settings.DEBUG:
            return True, 0, None

        sent_at = cache.get(f"otp:cooldown:{phone}")
        if sent_at:
            elapsed = time.time() - sent_at
            if elapsed < _OTP_COOLDOWN_SEC:
                return False, int(_OTP_COOLDOWN_SEC - elapsed), "cooldown"

        daily_count = cache.get(f"otp:daily:{phone}") or 0
        if daily_count >= _OTP_DAILY_LIMIT:
            return False, _OTP_DAILY_TTL, "daily_limit"

        return True, 0, None

    @classmethod
    def mark_sent(cls, phone: str):
        """OTP muvaffaqiyatli yuborilgach chastota counterlarini yangilash."""
        if settings.DEBUG:
            return
        cache.set(f"otp:cooldown:{phone}", time.time(), timeout=_OTP_COOLDOWN_SEC)
        try:
            cache.incr(f"otp:daily:{phone}")
        except ValueError:
            # Birinchi marta — set qilish, TTL 24h
            cache.set(f"otp:daily:{phone}", 1, timeout=_OTP_DAILY_TTL)

    @classmethod
    def generate(
        cls,
        phone,
        purpose,
        full_name="",
        role="",
        telegram_chat_id=None,
        referral_code="",
        sex="",
    ):
        # Avvalgi ishlatilmagan kodlarni bekor qilish
        cls.objects.filter(phone=phone, purpose=purpose, is_used=False).update(
            is_used=True
        )

        code = "".join(random.choices(string.digits, k=settings.OTP_LENGTH))
        expires_at = timezone.now() + timezone.timedelta(
            minutes=settings.OTP_EXPIRE_MINUTES
        )

        return cls.objects.create(
            phone=phone,
            code=code,
            purpose=purpose,
            full_name=full_name,
            role=role,
            telegram_chat_id=telegram_chat_id,
            referral_code=referral_code,
            sex=sex,
            expires_at=expires_at,
        )

    @classmethod
    def _consume_active_otp(cls, filter_kwargs: dict, code: str):
        """OTP'ni atomic'da topib tekshirish.

        select_for_update() row'ni lock qiladi va atomic transaction ichida
        attempts oshirish — 2 ta parallel hujum 5×N marotaba urinish bilan
        OTP_MAX_ATTEMPTS chegarasidan o'tib keta olmaydi.

        Return: (OTPCode, success). OTP topilmasa yoki muddati tugagan bo'lsa
        (None, False) qaytaradi.
        """
        max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
        with transaction.atomic():
            active_otp = (
                cls.objects.select_for_update()
                .filter(is_used=False, **filter_kwargs)
                .order_by("-created_at")
                .first()
            )
            if not active_otp or active_otp.is_expired:
                return None, False

            if active_otp.code != code:
                active_otp.attempts += 1
                if active_otp.attempts >= max_attempts:
                    active_otp.is_used = True
                    active_otp.save(update_fields=["attempts", "is_used"])
                else:
                    active_otp.save(update_fields=["attempts"])
                return active_otp, False

            active_otp.is_used = True
            active_otp.save(update_fields=["is_used"])
            return active_otp, True

    @classmethod
    def _is_bypass_phone(cls, phone, code):
        bypass_phones = getattr(settings, "BYPASS_PHONE_NUMBERS", [])
        return phone in bypass_phones and code == BYPASS_OTP_CODE

    @classmethod
    def _consume_test_otp(cls, phone, code):
        """Bypass-raqam yoki default-test-OTP holatini ko'rib chiqadi.

        Return:
            OTPCode — test/bypass kod mos keldi (oxirgi OTP consume qilinadi
                      yoki fake OTPCode qaytariladi)
            None    — test/bypass holati emas (oddiy OTP tekshiruvi kerak)
        """
        # Bypass raqamlar — har muhitda "0000" kod bilan o'tadi.
        is_bypass = cls._is_bypass_phone(phone, code)
        # Test OTP code — faqat default test foydalanuvchilar uchun (99800 prefix).
        # Production'da settings.DEFAULT_OTP_CODE = None bo'ladi (DEBUG only).
        default_otp = getattr(settings, "DEFAULT_OTP_CODE", None)
        is_test = bool(default_otp) and code == default_otp and phone.startswith("99800")
        if not (is_bypass or is_test):
            return None

        latest = cls.objects.filter(phone=phone).order_by("-created_at").first()
        if latest:
            latest.is_used = True
            latest.save(update_fields=["is_used"])
            return latest
        return cls(phone=phone, code=code, purpose="login")

    @classmethod
    def verify_any(cls, phone, code):
        """Purpose'siz OTP tekshiruvi — unified `/auth/verify` uchun.

        Bot ikki yo'l bilan kod beradi: register (yangi user) yoki login
        (mavjud user). Frontend purpose'ni bilmaydi — backend OTP yozuvini
        topib, uning purpose va metadata'sidan foydalanadi.
        """
        # Bypass-raqam yoki default-test-OTP holati (har muhitda "0000",
        # DEBUG/test'da DEFAULT_OTP_CODE).
        test_otp = cls._consume_test_otp(phone, code)
        if test_otp is not None:
            return test_otp

        active_otp, ok = cls._consume_active_otp({"phone": phone}, code)
        return active_otp if ok else None
