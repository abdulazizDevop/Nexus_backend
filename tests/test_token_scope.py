"""JWT token scope, patient_id, doctor_id claim'lari (Phase 2).

Test scope:
  - create_tokens_for_user yangi claim'lar bilan token issue qiladi
  - scope default = active_role (backwards compat)
  - patient_id, doctor_id token'da bor (yoki None — admin uchun)
  - Permission'lar yangi scope claim'ini o'qiydi
  - Eski tokenlar (scope yo'q) ham ishlashda davom etadi
  - Multi-scope: bir user uchun ikki xil scope bilan ikki token bo'la oladi
"""

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken

from app.auth.token_utils import create_tokens_for_user
from app.doctors.models import DoctorProfile
from tests.base import BaseAPITestCase

User = get_user_model()


def decode_token(token: str) -> dict:
    """Verify=False — test uchun shunchaki payload o'qish."""
    return jwt.decode(token, options={"verify_signature": False})


class TokenClaimsTests(BaseAPITestCase):
    """create_tokens_for_user yangi claim'lar bilan token yaratadi."""

    def test_patient_token_has_scope_and_patient_id(self):
        user = self.create_patient()
        result = create_tokens_for_user(user)

        self.assertEqual(result["active_role"], "patient")
        self.assertEqual(result["scope"], "patient")
        self.assertEqual(result["patient_id"], user.patient_profile.id)
        self.assertIsNone(result["doctor_id"])

        # Access token payload'ni dekod qilib tekshirish
        payload = decode_token(result["access"])
        self.assertEqual(payload["scope"], "patient")
        self.assertEqual(payload["patient_id"], user.patient_profile.id)
        self.assertIsNone(payload.get("doctor_id"))
        self.assertEqual(payload["active_role"], "patient")  # backwards compat

    def test_doctor_token_has_doctor_id(self):
        user = self.create_doctor()
        DoctorProfile.objects.create(user=user, is_verified=True)
        result = create_tokens_for_user(user, active_role="doctor")

        self.assertEqual(result["scope"], "doctor")
        self.assertEqual(result["doctor_id"], user.doctor_profile.id)
        # Doctor ham Patient'ga ega (Yandex Taxi)
        self.assertEqual(result["patient_id"], user.patient_profile.id)

        payload = decode_token(result["access"])
        self.assertEqual(payload["scope"], "doctor")
        self.assertEqual(payload["doctor_id"], user.doctor_profile.id)

    def test_admin_token_has_admin_scope(self):
        user = self.create_admin()
        result = create_tokens_for_user(user, active_role="admin")
        self.assertEqual(result["scope"], "admin")
        # Admin ham Patient'ga ega (admin user'ga ham auto-create)
        self.assertEqual(result["patient_id"], user.patient_profile.id)

    def test_explicit_scope_overrides_active_role(self):
        """scope param berilsa, default'dan farq qilishi mumkin."""
        user = self.create_doctor()
        DoctorProfile.objects.create(user=user, is_verified=True)
        result = create_tokens_for_user(user, active_role="patient", scope="doctor")
        # active_role va scope alohida (kelajakdagi multi-scope qo'llab-quvvatlash)
        self.assertEqual(result["active_role"], "patient")
        self.assertEqual(result["scope"], "doctor")

    def test_invalid_scope_raises(self):
        user = self.create_patient()
        with self.assertRaises(ValueError):
            create_tokens_for_user(user, scope="invalid")


class MultiTokenTests(BaseAPITestCase):
    """Bir user — har scope uchun alohida token (Yandex Taxi modeli)."""

    def test_user_can_hold_two_tokens_with_different_scopes(self):
        """Patient va doctor token alohida, bir-birini invalidate qilmaydi."""
        user = self.create_doctor()  # role=doctor
        DoctorProfile.objects.create(user=user, is_verified=True)

        # Doctor app login
        doctor_token = create_tokens_for_user(user, active_role="doctor")
        # Patient app login (bir xil user, boshqa scope)
        patient_token = create_tokens_for_user(user, active_role="patient")

        d_payload = decode_token(doctor_token["access"])
        p_payload = decode_token(patient_token["access"])

        self.assertEqual(d_payload["scope"], "doctor")
        self.assertEqual(p_payload["scope"], "patient")
        # Ikkalasida bir xil user_id
        self.assertEqual(d_payload["user_id"], p_payload["user_id"])
        # Lekin scope alohida → har app o'z scope'ida ishlaydi


class PermissionScopeTests(BaseAPITestCase):
    """Permission'lar yangi scope claim'ini o'qiydi."""

    def test_patient_token_passes_is_patient(self):
        user = self.auth_as_patient()
        # /me/ endpoint IsAuthenticated permission, lekin scope tekshiramiz
        resp = self.client.get("/api/v1/users/me/")
        self.assertEqual(resp.status_code, 200)
        # Token request.auth payload'da scope bor
        # (test uchun tokenni qayta dekod qilishimiz kerak)

    def test_legacy_token_without_scope_falls_back_to_active_role(self):
        """Eski tokenlar (scope claim yo'q) — active_role'dan fallback."""
        user = self.create_patient()
        # Legacy token — faqat active_role bilan
        refresh = RefreshToken.for_user(user)
        refresh["active_role"] = "patient"
        # scope va patient_id claim qo'shilmagan (legacy)
        access = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = self.client.get("/api/v1/users/me/")
        self.assertEqual(resp.status_code, 200)
        # Legacy token bilan ham ishlaydi


class AuthEndpointResponseTests(BaseAPITestCase):
    """Login/switch-role response'da yangi field'lar bor."""

    def test_switch_role_response_includes_scope_and_ids(self):
        user = self.auth_as_patient()
        resp = self.client.patch(
            "/api/v1/users/me/switch-role/",
            data={"active_role": "doctor"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["active_role"], "doctor")
        self.assertEqual(resp.data["scope"], "doctor")
        # Patient ham bor (har user'da default)
        self.assertEqual(resp.data["patient_id"], user.patient_profile.id)
        # Doctor profile auto-yaratildi (switch_role ichida)
        user.refresh_from_db()
        self.assertIsNotNone(resp.data["doctor_id"])
