"""JWT token utility'lari.

Token ichida active_role, scope va profile ID'lar saqlanadi. Har qurilma
(admin panel / patient app / doctor app) o'z tokeniga ega.

Claim'lar:
    - user_id (simplejwt default)
    - active_role: 'admin' | 'doctor' | 'patient' (legacy, backwards compat)
    - scope: 'admin' | 'doctor' | 'patient' (yangi — multi-token model uchun)
    - patient_id: Patient.id yoki None
    - doctor_id: DoctorProfile.id yoki None
    - context: 'admin' | 'mobile' | None (ixtiyoriy, debug uchun)

Multi-token model: bir user uch xil token chain'iga ega bo'lishi mumkin
(patient_token, doctor_token, admin_token). Har scope alohida — bir-birini
invalidate qilmaydi.

Permission classlari (core/permissions.py) `scope` (yangi) yoki `active_role`
(eski) ni o'qiydi. Eski tokenlar (scope yo'q) backwards compatible ishlaydi.
"""

from typing import Optional

from rest_framework_simplejwt.tokens import RefreshToken


_VALID_SCOPES = ("admin", "doctor", "patient")


def _resolve_active_role(user, requested: Optional[str]) -> str:
    """Foydalanuvchi uchun active_role aniqlaydi.

    Priority: requested (agar allowed_roles ichida bo'lsa), aks holda user.role.
    """
    allowed = list(user.allowed_roles)
    if requested:
        if requested in allowed:
            return requested
        raise ValueError(f"'{requested}' rolga ruxsat yo'q. Mumkin: {allowed}")
    return user.role


def _patient_id_for(user) -> Optional[int]:
    """User'ning Patient profile id'sini xavfsiz qaytaradi."""
    profile = getattr(user, "patient_profile", None)
    return profile.id if profile else None


def _doctor_id_for(user) -> Optional[int]:
    """User'ning DoctorProfile id'sini xavfsiz qaytaradi (verified yoki yo'q)."""
    profile = getattr(user, "doctor_profile", None)
    return profile.id if profile else None


def create_tokens_for_user(
    user,
    active_role: Optional[str] = None,
    context: Optional[str] = None,
    scope: Optional[str] = None,
    extra_claims: Optional[dict] = None,
) -> dict:
    """User uchun token juftligini yaratadi (access + refresh).

    Args:
        user: User instance
        active_role: 'admin' | 'doctor' | 'patient' (default=user.role)
        scope: 'admin' | 'doctor' | 'patient' (default=active_role)
        context: 'admin' | 'mobile' | None (audit uchun)
        extra_claims: qo'shimcha JWT claim'lar — default None,
            mavjud chaqiruvchilarga ta'sir yo'q.

    Returns:
        {
            "access": "<jwt>", "refresh": "<jwt>",
            "active_role": "<resolved>", "scope": "<resolved>",
            "patient_id": <int or None>, "doctor_id": <int or None>,
        }
    """
    # SECURITY: deaktivatsiya qilingan user'ga hech qanday kanal (bot, bypass,
    # test, SMS) token bera olmasligi uchun markaziy himoya — ban/deaktivatsiya
    # samarali bo'lsin.
    if not user.is_active:
        raise ValueError("Akkaunt bloklangan.")

    resolved_role = _resolve_active_role(user, active_role)
    resolved_scope = scope or resolved_role  # scope default = active_role
    if resolved_scope not in _VALID_SCOPES:
        raise ValueError(
            f"Noto'g'ri scope: '{resolved_scope}'. Faqat admin/doctor/patient."
        )
    # SECURITY: scope ham allowed_roles ichida bo'lishi shart — non-admin
    # user'ga admin scope berilishini oldini oladi (privilege escalation).
    allowed = list(user.allowed_roles)
    if resolved_scope not in allowed:
        raise ValueError(
            f"Sizga '{resolved_scope}' scope'iga ruxsat yo'q. Mumkin: {allowed}"
        )

    patient_id = _patient_id_for(user)
    doctor_id = _doctor_id_for(user)

    refresh = RefreshToken.for_user(user)
    refresh["active_role"] = resolved_role  # backwards compat
    refresh["scope"] = resolved_scope
    refresh["patient_id"] = patient_id
    refresh["doctor_id"] = doctor_id
    if context:
        refresh["context"] = context
    for key, value in (extra_claims or {}).items():
        refresh[key] = value

    # access_token refresh'dan hamma claim'larni meros oladi (simplejwt)
    access = refresh.access_token

    return {
        "access": str(access),
        "refresh": str(refresh),
        "active_role": resolved_role,
        "scope": resolved_scope,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
    }


def _claim(token, key: str):
    """Validated token instance'dan claim'ni xavfsiz chiqaradi."""
    if not token:
        return None
    payload = getattr(token, "payload", None)
    return payload.get(key) if payload else None


def get_active_role_from_token(token) -> Optional[str]:
    return _claim(token, "active_role")


def get_scope_from_token(token) -> Optional[str]:
    """Validated token instance'dan scope claim'ini chiqaradi.

    Eski tokenlarda scope yo'q — None qaytaradi. Permission'lar fallback
    sifatida active_role'ga o'tadi.
    """
    return _claim(token, "scope")
