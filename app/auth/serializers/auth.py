from .common import *  # noqa: F401,F403


class AuthRequestSerializer(serializers.Serializer):
    """Unified auth — telefon yuborish (register yoki login farqlanmaydi).

    Ikki kanal:
      - `channel='bot'` (default): Telegram bot deeplink qaytariladi. Yangi
        user uchun ism + kontakt + referral bot ichida yig'iladi.
      - `channel='sms'`: Eskiz SMS orqali OTP yuboriladi. Yangi user uchun
        ism va referral keyin `/auth/auth/verify/` da yuboriladi (OTP'dan
        keyin — phone tasdiqlangach).

    Mavjud user uchun: backend Telegram (bog'langan bo'lsa) yoki SMS'ga
    yuboradi. Frontend `channel='sms'` orqali aniq SMS so'rashi mumkin.
    """

    phone = serializers.CharField(max_length=15)
    role = serializers.ChoiceField(
        choices=[("patient", "Patient"), ("doctor", "Doctor")],
        default="patient",
        help_text=(
            "Yangi user uchun default role. Mavjud user'da e'tiborsiz "
            "qoldiriladi (DB'dagi role ishlatiladi)."
        ),
    )
    channel = serializers.ChoiceField(
        choices=[("sms", "SMS"), ("bot", "Telegram bot")],
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Kanal tanlovi. Default — backend tanlaydi.",
    )

    def validate_phone(self, value):
        return validate_uz_phone(value)


class AuthVerifySerializer(serializers.Serializer):
    """Unified auth verify — OTP tasdiqlash.

    Backend OTP yozuvini tekshiradi va flow'ni aniqlaydi:
      - Mavjud user → JWT qaytariladi (login)
      - Yangi user, OTP'da full_name bor (bot register) → user yaratiladi, JWT
      - Yangi user, OTP'da full_name yo'q (SMS register) → registration_token
        qaytariladi (frontend /auth/complete-registration/ chaqirsin).
    """

    phone = serializers.CharField(max_length=15)
    code = serializers.CharField(max_length=10)
    active_role = serializers.ChoiceField(
        choices=["admin", "doctor", "patient"],
        required=False,
        allow_null=True,
        help_text="Qaysi rejimda kirish (token claim).",
    )
    context = serializers.ChoiceField(
        choices=["admin", "mobile", "web"],
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate_phone(self, value):
        return validate_uz_phone(value)


class CompleteRegistrationSerializer(serializers.Serializer):
    """SMS register'ning ikkinchi bosqichi — phone tasdiqlangach datalar yuboriladi.

    `registration_token` — `/auth/auth/verify/` qaytargan vaqtinchalik signed
    token (10 daqiqa amal qiladi). Token ichida tasdiqlangan phone bor —
    foydalanuvchi qayta o'zgartira olmaydi.
    """

    registration_token = serializers.CharField()
    full_name = serializers.CharField(max_length=255)
    role = serializers.ChoiceField(
        choices=[("patient", "Patient"), ("doctor", "Doctor")],
        default="patient",
    )
    sex = serializers.ChoiceField(
        choices=[("male", "Male"), ("female", "Female")],
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Jinsi — ixtiyoriy, kelajakda Patient profilda ham ishlatiladi.",
    )
    referral_code = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Ixtiyoriy — agar berilsa, doctor referral code'i tekshiriladi.",
    )
    active_role = serializers.ChoiceField(
        choices=["admin", "doctor", "patient"],
        required=False,
        allow_null=True,
    )
    context = serializers.ChoiceField(
        choices=["admin", "mobile", "web"],
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    def validate_full_name(self, value):
        value = (value or "").strip()
        if len(value) < 2:
            raise serializers.ValidationError("Iltimos, to'liq ismingizni kiriting.")
        return value
