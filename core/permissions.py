from typing import Optional

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from app.users.models import User


def _payload(request) -> Optional[dict]:
    """JWT payload'ni xavfsiz qaytaradi (yo'q bo'lsa None)."""
    if request is None:
        return None
    auth = getattr(request, "auth", None)
    return getattr(auth, "payload", None) if auth else None


def _active_role(user, request=None):
    """Foydalanuvchining hozirgi aktiv rolini qaytaradi.

    Priority:
      1. JWT `scope` claim (yangi — multi-token model)
      2. JWT `active_role` claim (legacy — Variant A)
      3. user.role (immutable registration roli)

    `user.active_role` (mutable, global/shared DB ustuni) ATAYLAB ishlatilmaydi:
    boshqa qurilmadan switch-role qilinsa, claim'siz eski tokenlar noto'g'ri
    rolga ruxsat oladi (cross-device authz leak). `get_request_role` bilan bir
    xil non-leaky mantiq.
    """
    payload = _payload(request)
    if payload:
        scope_claim = payload.get("scope")
        if scope_claim:
            return scope_claim
        legacy_claim = payload.get("active_role")
        if legacy_claim:
            return legacy_claim
    return user.role


def get_token_scope(request) -> Optional[str]:
    """JWT'dan scope claim'ini chiqaradi.

    Yangi tokenlar `scope` claim'ini ko'taradi. Eski tokenlarda — `active_role`
    fallback. Hech qanday claim yo'q bo'lsa — None.
    """
    payload = _payload(request)
    if not payload:
        return None
    return payload.get("scope") or payload.get("active_role")


def get_request_role(request) -> str:
    """Hozirgi so'rov qaysi rol-context'da bajarilayotganini qaytaradi.

    Token scope — yagona haqiqat manbai (per-session). Bir xil account boshqa
    qurilmadan boshqa rejimga switch qilsa ham, hozirgi so'rovning roli
    o'zgarmaydi (cross-device leak yo'q).

    Fallback `user.role` (immutable registration role) — `user.active_role` DB
    ustuniga TUTGILMAYDI (u global/shared, eski sessiyalarni iflos qiladi).
    """
    scope = get_token_scope(request)
    if scope:
        return scope
    user = getattr(request, "user", None)
    return getattr(user, "role", User.Role.PATIENT) if user else User.Role.PATIENT


# ___ Role-based (active_role bo'yicha — switch qilinadi) ___


class _ActiveRolePermission(BasePermission):
    """JWT scope / active_role bo'yicha tekshiruvchi permission base."""

    allowed_roles: tuple[str, ...] = ()

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and _active_role(request.user, request) in self.allowed_roles
        )


def _switch_hint(role: str) -> str:
    return (
        f"Bu endpoint faqat {role} rejimida ishlaydi. "
        f'PATCH /api/v1/users/me/switch-role/ {{"active_role": "{role}"}} yuboring.'
    )


class IsAdmin(_ActiveRolePermission):
    allowed_roles = (User.Role.ADMIN,)
    message = _switch_hint("admin")


class IsDoctor(_ActiveRolePermission):
    allowed_roles = (User.Role.DOCTOR,)
    message = _switch_hint("doctor")


class IsPatient(_ActiveRolePermission):
    allowed_roles = (User.Role.PATIENT,)
    message = _switch_hint("patient")


class DoctorNotVerified(PermissionDenied):
    """Doctor profili hali admin tomonidan tasdiqlanmagan — 403.

    `code` frontend uchun — "tasdiq kutilmoqda" ekranini generic 403 (scope
    xato) dan ajratish uchun. Doctor profilini to'ldira oladi, lekin operatsion
    (bemor / pul / qabul / muolaja) endpointlarga kira olmaydi.
    """

    default_detail = (
        "Profilingiz hali admin tomonidan tasdiqlanmagan. "
        "Tasdiqlangach barcha imkoniyatlar ochiladi."
    )
    default_code = "doctor_not_verified"


class IsVerifiedDoctor(IsDoctor):
    """IsDoctor + `DoctorProfile.is_verified`. Tasdiqlanmagan doctor'ni bloklaydi.

    Avval doctor rejimini tekshiradi (IsDoctor scope). Doctor rejimida, biroq
    profili tasdiqlanmagan bo'lsa — `DoctorNotVerified` (403, code=doctor_not_verified).

    `is_verified` DB'dan har so'rovda o'qiladi (`request.user.is_verified_doctor`
    — reverse OneToOne, per-request cache) — JWT'ga bosilmaydi, shu bois admin
    tasdiqlagach KEYINGI so'rovda darrov kuchga kiradi (token refresh shart emas).

    Doctor OCHIQ qoladigan joylarda (o'z profili `me`, sertifikat) oddiy IsDoctor
    ishlatiladi — bu permission faqat operatsion endpointlar uchun.
    """

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False  # doctor rejimida emas — IsDoctor'ning odatiy 403 (switch-role)
        if not request.user.is_verified_doctor:
            raise DoctorNotVerified()
        return True


class IsDoctorOrPatient(_ActiveRolePermission):
    allowed_roles = (User.Role.DOCTOR, User.Role.PATIENT)


# ___ Admin type-based (asosiy role bo'yicha — SWITCH TA'SIR QILMAYDI) ___
# Admin type = kim ekanligi, active_role = hozir nima sifatida ishlayapti.
# Admin panel, support chat, tasdiqlash — asosiy role tekshiriladi.


class _AdminTypePermission(BasePermission):
    """Admin type bo'yicha tekshiruvchi permission base."""

    allowed_types: tuple[str, ...] = ()

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.ADMIN
            and request.user.admin_type in self.allowed_types
        )


class IsRootAdmin(BasePermission):
    """Root admin — ROOT_ADMIN_PHONE ga mos telefon. Super adminlarni manage qiladi."""

    message = (
        "Bu amal faqat root admin uchun. Super adminlarni yaratish/o'chirish "
        "yoki rolini o'zgartirish faqat root admin qo'lida."
    )

    def has_permission(self, request, view):
        return request.user.is_authenticated and getattr(
            request.user, "is_root_admin", False
        )


class IsSuperAdmin(_AdminTypePermission):
    allowed_types = (User.AdminType.SUPER,)


class IsSuperOrSimpleAdmin(_AdminTypePermission):
    allowed_types = (User.AdminType.SUPER, User.AdminType.SIMPLE)
