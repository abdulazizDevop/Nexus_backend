from django.test import override_settings
from rest_framework import status

from app.auth.models import OTPCode
from tests.base import BaseAPITestCase


@override_settings(DEFAULT_OTP_CODE="7777", DEFAULT_REFERRAL_CODE="TESTREF")
class AuthRequestTests(BaseAPITestCase):
    """Auth — Unified /auth/ endpoint (telefon yuborish).

    Backend qaytaradigan via:
      - via='bot'      → yangi user yoki Telegram bog'lanmagan, deeplink ham bor
      - via='telegram' → mavjud user, kod darrov Telegram orqali yuborildi
      - via='test'     → 99800... test user, DEFAULT_OTP_CODE bilan kirish
    """

    def test_auth_new_user_returns_bot_deeplink(self):
        """Yangi user uchun bot deeplink qaytadi"""
        resp = self.client.post(
            "/api/v1/auth/auth/",
            {"phone": "998901111111", "role": "patient"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "bot")
        self.assertIn("deeplink", resp.data)
        self.assertIn("auth_patient_", resp.data["deeplink"])

    def test_auth_existing_user_no_telegram_sms_fallback(self):
        """Mavjud user, telegram_chat_id yo'q → avtomatik SMS (Eskiz failed bo'lsa 502)"""
        from unittest.mock import patch

        self.create_patient(phone="998901234567", telegram_chat_id=None)
        with patch("app.auth.views.send_otp_via_sms", return_value=False):
            resp = self.client.post(
                "/api/v1/auth/auth/",
                {"phone": "998901234567", "role": "patient"},
            )
        # Eskiz fail bo'lsa 502, ishlasa 200 + via='sms'
        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)

    def test_auth_existing_user_with_telegram_sends_otp(self):
        """Mavjud user + telegram_chat_id bog'langan → kod darrov yuboriladi (botsiz)"""
        from unittest.mock import patch

        self.create_patient(phone="998901234567", telegram_chat_id=12345)
        with patch("app.auth.views.send_otp_via_telegram", return_value=True):
            resp = self.client.post(
                "/api/v1/auth/auth/",
                {"phone": "998901234567", "role": "patient"},
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "telegram")
        self.assertNotIn("deeplink", resp.data)

    def test_auth_existing_user_no_telegram_explicit_bot_returns_deeplink(self):
        """Mavjud user, Telegram bog'lanmagan + channel='bot' → bot deeplink"""
        self.create_patient(phone="998901234570", telegram_chat_id=None)
        resp = self.client.post(
            "/api/v1/auth/auth/",
            {"phone": "998901234570", "channel": "bot"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "bot")
        self.assertIn("deeplink", resp.data)

    def test_auth_existing_user_explicit_sms_channel(self):
        """`channel='sms'` aniq berilsa, Telegram bog'langan bo'lsa ham SMS yuboriladi"""
        from unittest.mock import patch

        self.create_patient(phone="998901234568", telegram_chat_id=99999)
        with patch("app.auth.views.send_otp_via_sms", return_value=True):
            resp = self.client.post(
                "/api/v1/auth/auth/",
                {"phone": "998901234568", "channel": "sms"},
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "sms")

    def test_auth_existing_user_no_telegram_uses_sms(self):
        """Mavjud user, Telegram'siz → avtomatik SMS"""
        from unittest.mock import patch

        self.create_patient(phone="998901234569", telegram_chat_id=None)
        with patch("app.auth.views.send_otp_via_sms", return_value=True):
            resp = self.client.post(
                "/api/v1/auth/auth/",
                {"phone": "998901234569"},
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "sms")

    def test_auth_sms_register_only_phone_needed(self):
        """SMS register: /auth/auth/ faqat phone'ni so'raydi (datalar verify'dan keyin)"""
        from unittest.mock import patch

        with patch("app.auth.views.send_otp_via_sms", return_value=True):
            resp = self.client.post(
                "/api/v1/auth/auth/",
                {"phone": "998901111200", "role": "patient", "channel": "sms"},
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "sms")
        otp = OTPCode.objects.filter(phone="998901111200", purpose="register").first()
        self.assertIsNotNone(otp)
        self.assertEqual(otp.role, "patient")
        # SMS register'da OTP'da full_name yo'q — verify'dan keyin yuboriladi
        self.assertEqual(otp.full_name, "")

    def test_auth_test_user(self):
        """99800... test user — via=test, DEFAULT_OTP_CODE bilan kirish"""
        resp = self.client.post(
            "/api/v1/auth/auth/",
            {"phone": "998000000001", "role": "patient"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["via"], "test")
        self.assertTrue(resp.data["is_test_user"])

    def test_auth_doctor_role(self):
        """Doctor role bilan yangi user — bot deeplink"""
        resp = self.client.post(
            "/api/v1/auth/auth/",
            {"phone": "998901111112", "role": "doctor"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("auth_doctor_", resp.data["deeplink"])

    def test_auth_invalid_role(self):
        """POST /auth/auth/ — noto'g'ri role"""
        resp = self.client.post(
            "/api/v1/auth/auth/",
            {"phone": "998901111114", "role": "invalid_role"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_auth_missing_phone(self):
        """POST /auth/auth/ — phone yo'q bo'lsa xato"""
        resp = self.client.post(
            "/api/v1/auth/auth/",
            {"role": "patient"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(DEFAULT_OTP_CODE="7777")
class AuthVerifyTests(BaseAPITestCase):
    """Auth — Unified /auth/verify/ endpoint (OTP tasdiqlash)"""

    def test_verify_register_creates_user(self):
        """POST /auth/auth/verify/ — yangi user uchun OTP'da ism+role bo'lsa yaratiladi"""
        otp = OTPCode.generate(
            phone="998901111115",
            purpose="register",
            full_name="Test User",
            role="patient",
        )
        resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111115", "code": otp.code},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["is_new"])
        self.assertIn("tokens", resp.data)
        self.assertIn("access", resp.data["tokens"])

    def test_verify_login_existing_user(self):
        """POST /auth/auth/verify/ — mavjud user uchun login OTP token qaytaradi"""
        self.create_patient(phone="998901234567", telegram_chat_id=12345)
        otp = OTPCode.generate(phone="998901234567", purpose="login")
        resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901234567", "code": otp.code},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["is_new"])
        self.assertIn("tokens", resp.data)

    def test_verify_sms_new_user_returns_registration_token(self):
        """SMS register: verify yangi user uchun registration_token qaytaradi (JWT yo'q)"""
        otp = OTPCode.generate(phone="998901111301", purpose="register", role="patient")
        resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111301", "code": otp.code},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_new"])
        self.assertTrue(resp.data["registration_required"])
        self.assertIn("registration_token", resp.data)
        self.assertNotIn("tokens", resp.data)

    def test_complete_registration_patient_creates_user(self):
        """Complete-registration: token + full_name → user yaratiladi va JWT keladi"""
        # 1. SMS verify → registration_token
        otp = OTPCode.generate(phone="998901111302", purpose="register", role="patient")
        verify_resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111302", "code": otp.code},
        )
        token = verify_resp.data["registration_token"]

        # 2. Complete-registration
        resp = self.client.post(
            "/api/v1/auth/complete-registration/",
            {
                "registration_token": token,
                "full_name": "SMS User",
                "role": "patient",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", resp.data)
        self.assertEqual(resp.data["user"]["full_name"], "SMS User")
        self.assertEqual(resp.data["user"]["role"], "patient")

    def test_complete_registration_doctor_without_referral(self):
        """Complete-registration: doctor uchun referral_code ixtiyoriy — referralsiz ham yaratiladi"""
        otp = OTPCode.generate(phone="998901111303", purpose="register", role="doctor")
        verify_resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111303", "code": otp.code},
        )
        token = verify_resp.data["registration_token"]

        resp = self.client.post(
            "/api/v1/auth/complete-registration/",
            {
                "registration_token": token,
                "full_name": "Doctor SMS",
                "role": "doctor",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("tokens", resp.data)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        new_doc = User.objects.get(phone="998901111303")
        self.assertEqual(new_doc.role, "doctor")
        self.assertIsNone(new_doc.referred_by_id)

    def test_complete_registration_doctor_with_valid_referral(self):
        """Complete-registration: doctor + to'g'ri referral_code → user yaratiladi"""
        seller = self.create_seller()
        otp = OTPCode.generate(phone="998901111304", purpose="register", role="doctor")
        verify_resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111304", "code": otp.code},
        )
        token = verify_resp.data["registration_token"]

        resp = self.client.post(
            "/api/v1/auth/complete-registration/",
            {
                "registration_token": token,
                "full_name": "Doctor SMS",
                "role": "doctor",
                "referral_code": seller.referral_code,
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        new_doc = User.objects.get(phone="998901111304")
        self.assertEqual(new_doc.role, "doctor")
        self.assertEqual(new_doc.referred_by_id, seller.id)

    def test_complete_registration_invalid_token(self):
        """Complete-registration: noto'g'ri token → 400"""
        resp = self.client.post(
            "/api/v1/auth/complete-registration/",
            {
                "registration_token": "noto-g-ri-token",
                "full_name": "Test",
                "role": "patient",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_registration_phone_already_exists(self):
        """Complete-registration: shu paytda boshqa joydan account ochilgan bo'lsa 400"""
        otp = OTPCode.generate(phone="998901111305", purpose="register", role="patient")
        verify_resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111305", "code": otp.code},
        )
        token = verify_resp.data["registration_token"]

        # Race: shu paytda account yaratildi
        self.create_patient(phone="998901111305", telegram_chat_id=None)

        resp = self.client.post(
            "/api/v1/auth/complete-registration/",
            {
                "registration_token": token,
                "full_name": "Late User",
                "role": "patient",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_doctor_with_referral_in_otp(self):
        """Doctor uchun OTP'dagi referral_code referred_by'ga aylanadi.

        Bot referral'ni validate qiladi va OTP'ga saqlaydi. Verify endpoint
        otp.referral_code ni o'qib User.referred_by'ni o'rnatadi.
        """
        seller = self.create_seller()
        otp = OTPCode.generate(
            phone="998901111125",
            purpose="register",
            full_name="Doctor Test",
            role="doctor",
            referral_code=seller.referral_code,
        )
        resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111125", "code": otp.code},
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # Yangi doctor referred_by orqali seller'ga bog'langan bo'lishi kerak
        from django.contrib.auth import get_user_model
        User = get_user_model()
        new_user = User.objects.get(phone="998901111125")
        self.assertEqual(new_user.role, "doctor")
        self.assertEqual(new_user.referred_by_id, seller.id)

    def test_verify_wrong_code(self):
        """POST /auth/auth/verify/ — noto'g'ri OTP"""
        OTPCode.generate(
            phone="998901111116", purpose="register", full_name="Test", role="patient"
        )
        resp = self.client.post(
            "/api/v1/auth/auth/verify/",
            {"phone": "998901111116", "code": "0000"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class LogoutTests(BaseAPITestCase):
    """Auth — Logout"""

    def test_logout_success(self):
        """POST /auth/logout/ — refresh tokenni blacklist qiladi"""
        user = self.create_patient()
        refresh = self.authenticate(user)
        resp = self.client.post(
            "/api/v1/auth/logout/",
            {
                "refresh": str(refresh),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_logout_invalid_token(self):
        """POST /auth/logout/ — noto'g'ri token"""
        user = self.create_patient()
        self.authenticate(user)
        resp = self.client.post(
            "/api/v1/auth/logout/",
            {
                "refresh": "invalid_token",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_unauthenticated(self):
        """POST /auth/logout/ — login qilmagan user"""
        resp = self.client.post(
            "/api/v1/auth/logout/",
            {
                "refresh": "some_token",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class TokenRefreshTests(BaseAPITestCase):
    """Auth — Token refresh"""

    def test_refresh_success(self):
        """POST /auth/token/refresh/ — yangi access token olish"""
        user = self.create_patient()
        refresh = self.authenticate(user)
        self.client.credentials()  # auth olib tashlash
        resp = self.client.post(
            "/api/v1/auth/token/refresh/",
            {
                "refresh": str(refresh),
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)

    def test_refresh_invalid_token(self):
        """POST /auth/token/refresh/ — noto'g'ri refresh token"""
        resp = self.client.post(
            "/api/v1/auth/token/refresh/",
            {
                "refresh": "invalid",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class ReferralTests(BaseAPITestCase):
    """Auth — Referral code"""

    def test_referral_doctor_success(self):
        """GET /auth/referral/{code}/ — doctor referral code"""
        doctor = self.create_doctor()
        resp = self.client.get(f"/api/v1/auth/referral/{doctor.referral_code}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["role"], "doctor")

    def test_referral_invalid_code(self):
        """GET /auth/referral/{code}/ — noto'g'ri code"""
        resp = self.client.get("/api/v1/auth/referral/INVALID1/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
