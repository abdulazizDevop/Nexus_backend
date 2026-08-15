import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as _BaseTokenRefreshView

from app.auth.models import BYPASS_OTP_CODE, OTPCode
from app.auth.serializers import (
    AccountDeletionRequestSerializer,
    AuthRequestSerializer,
    AuthVerifySerializer,
    CompleteRegistrationSerializer,
    LogoutSerializer,
)
from app.auth.token_utils import create_tokens_for_user
from app.notifications.models import DeviceToken
from app.users.models import AccountDeletionRequest
from core.redact import mask_email, mask_phone
from services.sms import send_otp_via_sms
from services.storage import generate_download_url
from services.telegram import (
    get_auth_deeplink,
    send_account_deletion_notice,
    send_otp_via_telegram,
)

# SMS register'ning 2-bosqichida ishlatiladigan vaqtinchalik token sozlamalari
_REGISTRATION_TOKEN_SALT = "auth.registration"
_REGISTRATION_TOKEN_TTL_SEC = 600  # 10 daqiqa

User = get_user_model()
logger = logging.getLogger("mediik.auth")
security_logger = logging.getLogger("mediik.security.referral")



def _is_valid_doctor_referral(code: str) -> bool:
    """Doctor referral code validatsiyasi (sync versiya).

    Qabul qilinadi:
      - DEFAULT_REFERRAL_CODE (dev/test uchun)
      - Mavjud admin yoki doctor referral_code'i
    """
    if not code:
        return False
    default_code = getattr(settings, "DEFAULT_REFERRAL_CODE", None)
    if default_code and code == default_code:
        return True
    return User.objects.filter(
        referral_code=code, role__in=[User.Role.ADMIN, User.Role.DOCTOR]
    ).exists()


def _user_payload(user, tokens: dict) -> dict:
    """Auth response uchun standart user + tokens dict."""
    return {
        "user": {
            "id": user.id,
            "phone": user.phone,
            "full_name": user.full_name,
            "role": user.role,
            "active_role": tokens["active_role"],
            "scope": tokens["scope"],
            "allowed_roles": user.allowed_roles,
            "patient_id": tokens["patient_id"],
            "doctor_id": tokens["doctor_id"],
            "referral_code": user.referral_code,
        },
        "tokens": {
            "access": tokens["access"],
            "refresh": tokens["refresh"],
        },
    }


def _link_telegram_chat(user, chat_id) -> None:
    """user.telegram_chat_id'ni xavfsiz yangilaydi (unique konflikt himoyasi).

    telegram_chat_id `unique=True`. Agar shu chat_id allaqachon boshqa user'ga
    bog'langan bo'lsa, eski egasidan ajratib (NULL qilib) so'ng joriy user'ga
    biriktiramiz — IntegrityError → 500 o'rniga. Bir Telegram akkaunti faqat
    bitta Mediik user'ga bog'langan bo'lishi mumkin (oxirgi login g'olib).
    """
    if not chat_id or user.telegram_chat_id == chat_id:
        return
    try:
        with transaction.atomic():
            user.telegram_chat_id = chat_id
            user.save(update_fields=["telegram_chat_id"])
    except IntegrityError:
        # Konflikt — chat_id boshqa user'da. Eski egasidan ajratib qayta urinamiz.
        with transaction.atomic():
            User.objects.filter(telegram_chat_id=chat_id).exclude(pk=user.pk).update(
                telegram_chat_id=None
            )
            user.telegram_chat_id = chat_id
            user.save(update_fields=["telegram_chat_id"])


def _otp_send_failed_response() -> Response:
    return Response(
        {"detail": "Yuborib bo'lmadi. Iltimos, keyinroq urinib ko'ring."},
        status=status.HTTP_502_BAD_GATEWAY,
    )


def _send_sms_otp_response(phone: str, otp, success_message: str) -> Response:
    """OTP'ni SMS orqali yuboradi va standart javob qaytaradi.

    Muvaffaqiyat → 200 (mark_sent + via=sms), aks holda yagona 502
    (_otp_send_failed_response) — barcha SMS-fail holatlari bir xil javobga ega.
    """
    if send_otp_via_sms(phone, otp.code):
        OTPCode.mark_sent(phone)
        return Response(
            {"phone": phone, "via": "sms", "message": success_message},
            status=status.HTTP_200_OK,
        )
    return _otp_send_failed_response()


