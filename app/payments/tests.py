"""ATMOS ASL payout integratsiyasi uchun testlar.

Mock'lar:
- services.payments.atmos_asl.atmos_asl_client — HTTP qatlami (requests)
- Cache (Redis) — Django default test backend (locmem) ishlatiladi

Test'lar Django default DB'da ishlaydi (settings env'iga qarab SQLite yoki Postgres).
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from app.doctors.models import DoctorProfile, Specialty
from app.payments.atmos_asl_service import (
    _decimal_to_tiyin,
    initiate_atmos_payout,
    register_card_if_needed,
)
from app.payments.models import (
    DoctorBalance,
    DoctorPayoutCard,
    PayoutRequest,
)
from services.payments.atmos_asl import (
    STATE_FAILED,
    STATE_FINISHED,
    STATE_PENDING,
    AtmosAslClient,
    AtmosAslError,
)

User = get_user_model()


# ---------- Pure helpers ----------


class DecimalToTiyinTests(TestCase):
    def test_basic_conversion(self):
        self.assertEqual(_decimal_to_tiyin(Decimal("50000")), 5000000)
        self.assertEqual(_decimal_to_tiyin(Decimal("1000")), 100000)
        self.assertEqual(_decimal_to_tiyin(Decimal("0.50")), 50)

    def test_zero(self):
        self.assertEqual(_decimal_to_tiyin(Decimal("0")), 0)

    def test_does_not_lose_precision(self):
        # 99.99 so'm = 9999 tiyin
        self.assertEqual(_decimal_to_tiyin(Decimal("99.99")), 9999)


# ---------- Client URL parsing ----------


@override_settings(
    ATMOS_ASL={
        "USERNAME": "test_user",
        "PASSWORD": "test_pass",
        "BASE_URL": "https://apigw.atmos.uz/out/1.0.0/asl",
        "TOKEN_CACHE_TTL": 3000,
        "POLL_MAX_RETRIES": 12,
        "POLL_COUNTDOWN_SEC": 5,
        "MIN_DEPOSIT_WARN_SUM": 1000000,
    }
)
class AtmosAslClientTests(TestCase):
    def test_token_url_strips_path(self):
        """Token endpoint base_url'dan path qismini olib tashlashi kerak."""
        client = AtmosAslClient()
        self.assertEqual(client._token_url(), "https://apigw.atmos.uz/token")

    def test_is_configured_true(self):
        client = AtmosAslClient()
        self.assertTrue(client.is_configured())

    def test_get_transaction_requires_id_or_ext(self):
        client = AtmosAslClient()
        with self.assertRaises(ValueError):
            client.get_transaction()


@override_settings(
    ATMOS_ASL={
        "USERNAME": "",
        "PASSWORD": "",
        "BASE_URL": "https://apigw.atmos.uz/out/1.0.0/asl",
        "TOKEN_CACHE_TTL": 3000,
        "POLL_MAX_RETRIES": 12,
        "POLL_COUNTDOWN_SEC": 5,
        "MIN_DEPOSIT_WARN_SUM": 1000000,
    }
)
class AtmosAslClientNotConfiguredTests(TestCase):
    def test_is_configured_false_when_credentials_missing(self):
        client = AtmosAslClient()
        self.assertFalse(client.is_configured())


# ---------- Service: register_card_if_needed ----------


class RegisterCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Kardiolog", icon="❤️")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )

    def _make_card(self, **kwargs):
        defaults = {
            "doctor": self.doctor,
            "card_number": "8600331234567890",
            "card_holder": "DOCTOR ALI",
            "expiry_month": 12,
            "expiry_year": 49,
        }
        defaults.update(kwargs)
        return DoctorPayoutCard.objects.create(**defaults)

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_skips_if_already_registered(self, mock_client):
        card = self._make_card(atmos_asl_card_id=42)
        result = register_card_if_needed(card)
        self.assertEqual(result, 42)
        mock_client.card_info.assert_not_called()

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_registers_and_saves_id(self, mock_client):
        mock_client.card_info.return_value = {
            "data": {
                "id": 99,
                "name": "DOCTOR ALI",
                "pan": "860033******7890",
                "expiry": "1249",
                "phone": "998900000000",
                "processing_type": "UZCARD",
            },
            "code": 0,
        }
        card = self._make_card()
        result = register_card_if_needed(card)
        self.assertEqual(result, 99)

        card.refresh_from_db()
        self.assertEqual(card.atmos_asl_card_id, 99)
        self.assertEqual(card.atmos_asl_phone, "998900000000")
        self.assertEqual(card.atmos_asl_processing_type, "UZCARD")

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_raises_on_invalid_pan_length(self, mock_client):
        # 16 raqamdan kam — ASL chaqirilmaydi
        card = self._make_card(card_number="12345")
        with self.assertRaises(AtmosAslError) as ctx:
            register_card_if_needed(card)
        self.assertEqual(ctx.exception.code, "invalid_card")
        mock_client.card_info.assert_not_called()

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_raises_on_missing_id_in_response(self, mock_client):
        mock_client.card_info.return_value = {"data": {}, "code": 0}
        card = self._make_card()
        with self.assertRaises(AtmosAslError) as ctx:
            register_card_if_needed(card)
        self.assertEqual(ctx.exception.code, "invalid_response")


# ---------- Service: initiate_atmos_payout ----------


class InitiateAtmosPayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Kardiolog", icon="❤️")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        DoctorBalance.objects.create(
            doctor=cls.doctor, balance=Decimal("100000.00")
        )

    def _make_payout(self, amount=Decimal("50000.00"), **kwargs):
        card = DoctorPayoutCard.objects.create(
            doctor=self.doctor,
            card_number="8600331234567890",
            card_holder="DOCTOR ALI",
            expiry_month=12,
            expiry_year=49,
            atmos_asl_card_id=99,  # avval registratsiya qilingan
        )
        defaults = {
            "doctor": self.doctor,
            "amount": amount,
            "card": card,
            "card_number": card.card_number,
            "card_holder": card.card_holder,
        }
        defaults.update(kwargs)
        return PayoutRequest.objects.create(**defaults)

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_state_4_marks_completed_and_decreases_balance(self, mock_client):
        # /create → state=2; /apply → state=4 (FINISHED)
        mock_client.create_transaction.return_value = {
            "data": {"transaction_id": 2000557, "state": 2},
            "code": 0,
        }
        mock_client.apply_transaction.return_value = {
            "data": {"transaction_id": 2000557, "state": STATE_FINISHED},
            "code": 0,
        }

        payout = self._make_payout()
        result = initiate_atmos_payout(payout)

        self.assertTrue(result["completed"])
        self.assertFalse(result.get("polling", False))
        self.assertEqual(result["state"], STATE_FINISHED)

        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.COMPLETED)
        self.assertEqual(payout.atmos_asl_transaction_id, 2000557)
        self.assertTrue(payout.atmos_asl_ext_id)  # uuid yaratilgan
        self.assertEqual(payout.method, PayoutRequest.Method.ATMOS_ASL)

        # DoctorBalance kamayganini tekshiramiz
        balance = DoctorBalance.objects.get(doctor=self.doctor)
        self.assertEqual(balance.balance, Decimal("50000.00"))
        self.assertEqual(balance.total_withdrawn, Decimal("50000.00"))

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_state_5_marks_rejected_and_keeps_balance(self, mock_client):
        mock_client.create_transaction.return_value = {
            "data": {"transaction_id": 2000558, "state": 2},
            "code": 0,
        }
        mock_client.apply_transaction.return_value = {
            "data": {
                "transaction_id": 2000558,
                "state": STATE_FAILED,
                "billing_error_message": "Insufficient funds",
            },
            "code": 0,
        }

        payout = self._make_payout()
        result = initiate_atmos_payout(payout)

        self.assertFalse(result["completed"])
        self.assertEqual(result["state"], STATE_FAILED)

        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.REJECTED)
        self.assertIn("Insufficient funds", payout.atmos_asl_error)

        # Balans o'zgarmagan
        balance = DoctorBalance.objects.get(doctor=self.doctor)
        self.assertEqual(balance.balance, Decimal("100000.00"))

    @patch("app.payments.atmos_asl_service._schedule_poll")
    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_state_13_schedules_polling(self, mock_client, mock_schedule):
        mock_client.create_transaction.return_value = {
            "data": {"transaction_id": 2000559, "state": 2},
            "code": 0,
        }
        mock_client.apply_transaction.return_value = {
            "data": {"transaction_id": 2000559, "state": STATE_PENDING},
            "code": 0,
        }

        payout = self._make_payout()
        result = initiate_atmos_payout(payout)

        self.assertFalse(result["completed"])
        self.assertTrue(result["polling"])
        mock_schedule.assert_called_once_with(payout.id)

        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.PENDING)
        self.assertEqual(
            payout.sub_status, PayoutRequest.SubStatus.ATMOS_PROCESSING
        )

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_create_failure_marks_rejected(self, mock_client):
        mock_client.create_transaction.side_effect = AtmosAslError(
            500, "Card not found"
        )

        payout = self._make_payout()
        with self.assertRaises(AtmosAslError):
            initiate_atmos_payout(payout)

        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.REJECTED)
        self.assertIn("Card not found", payout.atmos_asl_error)

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_raises_if_payout_not_pending(self, mock_client):
        payout = self._make_payout()
        payout.status = PayoutRequest.Status.COMPLETED
        payout.save(update_fields=["status"])

        with self.assertRaises(ValueError):
            initiate_atmos_payout(payout)
        mock_client.create_transaction.assert_not_called()


# ---------- Idempotency ----------


class IdempotencyTests(TestCase):
    """Bir xil payout 2 marta complete qilinmasligini tekshirish."""

    @classmethod
    def setUpTestData(cls):
        cls.specialty = Specialty.objects.create(name="Kardiolog", icon="❤️")
        cls.doctor_user = User.objects.create_user(
            phone="+998901111111", full_name="Doctor", role=User.Role.DOCTOR
        )
        cls.doctor = DoctorProfile.objects.create(
            user=cls.doctor_user, specialty=cls.specialty, is_verified=True
        )
        DoctorBalance.objects.create(
            doctor=cls.doctor, balance=Decimal("100000.00")
        )

    @patch("app.payments.atmos_asl_service.atmos_asl_client")
    def test_mark_completed_is_idempotent(self, mock_client):
        """Allaqachon COMPLETED payout uchun _mark_completed balansni qayta kamaytirmaydi."""
        from app.payments.atmos_asl_service import _mark_completed

        card = DoctorPayoutCard.objects.create(
            doctor=self.doctor,
            card_number="8600331234567890",
            card_holder="DOCTOR",
            expiry_month=12,
            expiry_year=49,
            atmos_asl_card_id=99,
        )
        payout = PayoutRequest.objects.create(
            doctor=self.doctor,
            amount=Decimal("30000.00"),
            card=card,
            card_number=card.card_number,
            card_holder=card.card_holder,
            status=PayoutRequest.Status.COMPLETED,  # avval complete
            atmos_asl_transaction_id=12345,
        )

        # Balansga teginmaslik kerak
        initial_balance = DoctorBalance.objects.get(doctor=self.doctor).balance

        _mark_completed(payout, state=STATE_FINISHED, data={})

        balance = DoctorBalance.objects.get(doctor=self.doctor)
        self.assertEqual(balance.balance, initial_balance)
        self.assertEqual(balance.total_withdrawn, Decimal("0"))
