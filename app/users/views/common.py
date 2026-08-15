import logging
import uuid
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import (
    Avg,
    Count,
    DateTimeField,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from app.auth.serializers import LinkDoctorSerializer
from app.auth.token_utils import create_tokens_for_user
from app.chat.models import ChatRoom, Message
from app.doctors.models import DoctorPatient, DoctorProfile
from app.notifications.models import Notification
from app.notifications.tasks import notify_by_key_user
from app.doctors.serializers import (
    AddByPhoneSerializer,
    DoctorListSerializer,
    DoctorPatientSerializer,
)
from app.payments.models import DoctorTariffPurchase
from app.users.models import AccountDeletionRequest, UserSettings
from app.users.serializers import (
    ChangeRoleSerializer,
    DeleteMyAccountSerializer,
    UserAdminDetailSerializer,
    UserAdminSerializer,
    UserFullInfoSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from core.permissions import (
    IsRootAdmin,
    IsSuperAdmin,
    IsSuperOrSimpleAdmin,
    get_request_role,
)
from services.storage import generate_avatar_key, generate_upload_url
from services.telegram import send_account_deletion_notice

User = get_user_model()
logger = logging.getLogger("mediik.users")

# Avatar yuklash cheklovlari — S3 cost va abuse'dan himoyalaydi.
AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5MB
AVATAR_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")


def _protect_root(target_user, request_user):
    """Root admin'ni boshqa admin o'zgartirmoqchi bo'lsa 403 qaytaradi."""
    if target_user.is_root_admin and target_user.id != request_user.id:
        return Response(
            {"detail": "Bu foydalanuvchini o'zgartirish mumkin emas."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _set_role(user, role, admin_type=None, blacklist=False):
    """User rolini (role + admin_type + is_staff) atomik o'rnatadi.

    is_staff har doim role==admin'ga moslanadi. blacklist=True bo'lsa eski
    JWT'lar yangi rolni "bilmasligi" sababli refresh tokenlar blacklist qilinadi
    (demote'da huquqlar yopilishi uchun).
    """
    user.role = role
    user.admin_type = admin_type
    user.is_staff = role == User.Role.ADMIN
    user.save(update_fields=["role", "admin_type", "is_staff"])
    if blacklist:
        _blacklist_user_tokens(user)




# --- Self-delete helpers ---
# delete_my_account action ichidan chaqiriladi. Atomic PII tozalash, token
# blacklist, audit yozuv va admin'ga telegram xabar — uchta mustaqil bosqich.
# Token blacklist va telegram bosqichlari xato bersa ham user uchun delete
# muvaffaqiyatli yakunlanadi (best-effort), faqat log yoziladi.


def _soft_delete_user(user, reason: str = "", refresh_token: str = "") -> None:
    """Soft-delete: PII anonimizatsiya + tokenlarni blacklist + audit + telegram."""
    original_phone = user.phone
    original_name = user.full_name  # anonimizatsiyadan OLDIN (keyin "" bo'ladi)

    with transaction.atomic():
        user.is_active = False
        # phone — CharField(max_length=15), unique. Anonimizatsiya qilamiz lekin
        # max_length'ga sig'ish kerak — aks holda DataError.
        _phone_max = user._meta.get_field("phone").max_length
        user.phone = f"d_{user.id}_{uuid.uuid4().hex}"[:_phone_max]
        user.full_name = ""
        user.avatar = None
        user.telegram_chat_id = None
        user.referral_code = None
        user.set_unusable_password()
        user.save(
            update_fields=[
                "is_active",
                "phone",
                "full_name",
                "avatar",
                "telegram_chat_id",
                "referral_code",
                "password",
            ]
        )

        # Doctor↔patient bog'lanishlarni uzish — deleted user UI ro'yxatlarda qolmasligi uchun
        DoctorPatient.objects.filter(patient=user).delete()
        doctor_profile = getattr(user, "doctor_profile", None)
        if doctor_profile:
            DoctorPatient.objects.filter(doctor=doctor_profile).delete()

        AccountDeletionRequest.objects.create(
            phone=original_phone,
            reason=reason,
            status=AccountDeletionRequest.Status.PROCESSED,
            processed_at=timezone.now(),
            admin_notes=f"Self-delete by user_id={user.id}",
        )

    _blacklist_user_tokens(user, refresh_token)
    _notify_admin_self_delete(user, original_phone, reason, original_name)


def _blacklist_user_tokens(user, refresh_token: str = "") -> None:
    """User'ning barcha refresh tokenlarini blacklist qiladi."""
    if refresh_token:
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            pass

    try:
        for ot in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=ot)
    except Exception as e:
        logger.warning("Token blacklist xatolik user_id=%s err=%s", user.id, e)


def _notify_admin_self_delete(
    user, original_phone: str, reason: str, original_name: str = ""
) -> None:
    """Root admin + qo'shimcha kuzatuvchilarga Telegram xabar (best-effort)."""
    try:
        import html

        text = (
            "🗑 <b>User akkauntini o'chirdi (self-delete)</b>\n\n"
            f"<b>Ism:</b> {html.escape(original_name or '—')}\n"
            f"<b>ID:</b> {user.id}\n"
            f"<b>Telefon:</b> {html.escape(original_phone or '—')}\n"
            f"<b>Rol:</b> {user.role}\n"
            f"<b>Sabab:</b> {html.escape(reason or '—')}"
        )
        send_account_deletion_notice(text)
    except Exception as e:
        logger.warning(
            "Self-delete telegram notify xatolik user_id=%s err=%s", user.id, e
        )
