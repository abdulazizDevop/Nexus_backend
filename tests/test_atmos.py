"""Atmos integratsiyasi — Atmos API mock qilingan holda.

Maqsad: credentials kelmasdan turib karta/to'lov/webhook flow'larini tekshirish.
Atmos serveriga real chiqilmaydi — `atmos_client` method'lari `unittest.mock.patch`
bilan almashtiriladi.
"""

import hashlib
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status

from app.payments.models import (
    AtmosSavedCard,
    Payment,
    ProPlan,
    ProSubscription,
)
from tests.base import BaseAPITestCase


ATMOS_TEST_SETTINGS = {
    "CONSUMER_KEY": "test_key",
    "CONSUMER_SECRET": "test_secret",
    "STORE_ID": "10869",
    "API_KEY": "test_webhook_api_key",
    "BASE_URL": "https://apigw.atmos.uz",
    "IS_TEST_MODE": True,
    "TOKEN_CACHE_TTL": 3000,
    "MAX_SAVED_CARDS": 5,
}


def _make_sign(store_id, transaction_id, account, amount, api_key):
    """Atmos webhook MD5 sign — docs formulasiga muvofiq.

    Prod verify_webhook() `account` field'idan hisoblaydi (docs `invoice` desa-da,
    amalda `account` keladi — services/payments/atmos.py:verify_webhook).
    """
    raw = f"{store_id}{transaction_id}{account}{amount}{api_key}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


@override_settings(ATMOS=ATMOS_TEST_SETTINGS)
class AtmosCardBindTests(BaseAPITestCase):
    """Karta biriktirish (init + confirm)."""

    def setUp(self):
        super().setUp()
        self.user = self.auth_as_patient(phone="998901111111")

    @patch("app.payments.atmos_views.atmos_client.bind_card_init")
    def test_bind_init_returns_atmos_tx_id(self, mock_init):
        mock_init.return_value = {"transaction_id": 12345, "phone": "998******11"}

        resp = self.client.post(
            "/api/v1/payments/atmos/cards/bind/",
            {"card_number": "8600000000000001", "expiry": "2505"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["atmos_tx_id"], 12345)
        mock_init.assert_called_once_with(
            card_number="8600000000000001", expiry="2505"
        )

    @patch("app.payments.atmos_views.atmos_client.bind_card_confirm")
    def test_bind_confirm_saves_card_and_marks_primary(self, mock_confirm):
        mock_confirm.return_value = {
            "data": {
                "card_id": 99,
                "card_token": "tok_abc",
                "pan": "860000******0001",
                "expiry": "2505",
            }
        }

        resp = self.client.post(
            "/api/v1/payments/atmos/cards/confirm/",
            {"atmos_tx_id": 12345, "otp": "1234"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        card = AtmosSavedCard.objects.get(atmos_card_id=99)
        self.assertEqual(card.user, self.user)
        self.assertEqual(card.card_token, "tok_abc")
        self.assertTrue(card.is_primary)

    @patch("app.payments.atmos_views.atmos_client.bind_card_init")
    def test_bind_blocks_when_max_cards_reached(self, mock_init):
        for i in range(5):
            AtmosSavedCard.objects.create(
                user=self.user,
                atmos_card_id=1000 + i,
                card_token=f"tok_{i}",
                pan_masked="860000******0000",
                expiry="2505",
            )

        resp = self.client.post(
            "/api/v1/payments/atmos/cards/bind/",
            {"card_number": "8600000000000099", "expiry": "2505"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        mock_init.assert_not_called()

    @patch("app.payments.atmos_views.atmos_client.bind_card_init")
    def test_bind_returns_atmos_error_as_400(self, mock_init):
        from services.payments.atmos import AtmosError

        mock_init.side_effect = AtmosError("STPIMS-ERR-019", "Karta topilmadi")

        resp = self.client.post(
            "/api/v1/payments/atmos/cards/bind/",
            {"card_number": "8600000000000001", "expiry": "2505"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["code"], "STPIMS-ERR-019")


@override_settings(ATMOS=ATMOS_TEST_SETTINGS)
class AtmosCardManageTests(BaseAPITestCase):
    """Karta o'chirish va primary qilish."""

    def setUp(self):
        super().setUp()
        self.user = self.auth_as_patient(phone="998902222222")
        self.card1 = AtmosSavedCard.objects.create(
            user=self.user,
            atmos_card_id=101,
            card_token="tok_1",
            pan_masked="860000******0001",
            expiry="2505",
            is_primary=True,
        )
        self.card2 = AtmosSavedCard.objects.create(
            user=self.user,
            atmos_card_id=102,
            card_token="tok_2",
            pan_masked="860000******0002",
            expiry="2606",
            is_primary=False,
        )

    @patch("app.payments.atmos_views.atmos_client.remove_card")
    def test_delete_card_removes_from_db_and_atmos(self, mock_remove):
        mock_remove.return_value = {}

        resp = self.client.delete(
            f"/api/v1/payments/atmos/cards/{self.card1.id}/"
        )

        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AtmosSavedCard.objects.filter(id=self.card1.id).exists())
        mock_remove.assert_called_once_with(101, "tok_1")

    @patch("app.payments.atmos_views.atmos_client.remove_card")
    def test_delete_primary_promotes_next_card(self, mock_remove):
        mock_remove.return_value = {}

        self.client.delete(f"/api/v1/payments/atmos/cards/{self.card1.id}/")

        self.card2.refresh_from_db()
        self.assertTrue(self.card2.is_primary)

    @patch("app.payments.atmos_views.atmos_client.remove_card")
    def test_delete_card_succeeds_even_if_atmos_errors(self, mock_remove):
        """Atmos tomonda karta yo'q bo'lib qolsa ham lokal DB tozalanadi."""
        from services.payments.atmos import AtmosError

        mock_remove.side_effect = AtmosError("STPIMS-ERR-022", "Karta topilmadi")

        resp = self.client.delete(
            f"/api/v1/payments/atmos/cards/{self.card1.id}/"
        )

        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(AtmosSavedCard.objects.filter(id=self.card1.id).exists())

    def test_make_primary_demotes_others(self):
        resp = self.client.post(
            f"/api/v1/payments/atmos/cards/{self.card2.id}/make-primary/"
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.card1.refresh_from_db()
        self.card2.refresh_from_db()
        self.assertFalse(self.card1.is_primary)
        self.assertTrue(self.card2.is_primary)


@override_settings(ATMOS=ATMOS_TEST_SETTINGS)
class AtmosPayTests(BaseAPITestCase):
    """To'lov boshlash va tasdiqlash (Pro obuna misolida)."""

    def setUp(self):
        super().setUp()
        self.user = self.auth_as_patient(phone="998903333333")
        self.card = AtmosSavedCard.objects.create(
            user=self.user,
            atmos_card_id=201,
            card_token="tok_pay",
            card_number="8600000000000001",
            pan_masked="860000******0001",
            expiry="2505",
            is_primary=True,
        )
        self.plan = ProPlan.objects.create(
            name="1 oy", duration_days=30, price=Decimal("50000.00")
        )

    @patch("app.payments.atmos_views.atmos_client.pay_pre_apply")
    @patch("app.payments.atmos_views.atmos_client.pay_create")
    def test_pay_creates_payment_and_calls_pre_apply(self, mock_create, mock_pre):
        mock_create.return_value = {"transaction_id": 7777}
        mock_pre.return_value = {}

        resp = self.client.post(
            "/api/v1/payments/atmos/pay/",
            {
                "saved_card_id": self.card.id,
                "purpose": "pro_subscription",
                "plan_id": self.plan.id,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["otp_required"])

        payment = Payment.objects.get(id=resp.data["payment_id"])
        self.assertEqual(payment.amount, Decimal("50000.00"))
        self.assertEqual(payment.provider, Payment.Provider.ATMOS)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider_transaction_id, "7777")

        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs["amount"], 5_000_000)
        self.assertEqual(call_kwargs["account"], str(payment.id))

        mock_pre.assert_called_once_with(
            transaction_id=7777,
            card_number=self.card.card_number,
            expiry=self.card.expiry,
        )

    def test_pay_rejects_unknown_card(self):
        resp = self.client.post(
            "/api/v1/payments/atmos/pay/",
            {
                "saved_card_id": 99999,
                "purpose": "pro_subscription",
                "plan_id": self.plan.id,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_pay_rejects_when_active_pro_exists(self):
        from django.utils import timezone

        ProSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=timezone.now(),
            expires_at=timezone.now() + timezone.timedelta(days=30),
        )

        resp = self.client.post(
            "/api/v1/payments/atmos/pay/",
            {
                "saved_card_id": self.card.id,
                "purpose": "pro_subscription",
                "plan_id": self.plan.id,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    @patch("app.payments.atmos_views.atmos_client.pay_pre_apply")
    @patch("app.payments.atmos_views.atmos_client.pay_create")
    def test_pay_marks_failed_on_atmos_error(self, mock_create, mock_pre):
        from services.payments.atmos import AtmosError

        mock_create.return_value = {"transaction_id": 8888}
        mock_pre.side_effect = AtmosError("STPIMS-ERR-010", "Karta bloklangan")

        resp = self.client.post(
            "/api/v1/payments/atmos/pay/",
            {
                "saved_card_id": self.card.id,
                "purpose": "pro_subscription",
                "plan_id": self.plan.id,
            },
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        payment = Payment.objects.get(provider_transaction_id="8888")
        self.assertEqual(payment.status, Payment.Status.FAILED)

    @patch("app.payments.atmos_views.atmos_client.pay_apply")
    def test_confirm_completes_payment_and_creates_subscription(self, mock_apply):
        mock_apply.return_value = {"ofd_url": "https://ofd.example/check/123"}

        payment = Payment.objects.create(
            user=self.user,
            amount=self.plan.price,
            provider=Payment.Provider.ATMOS,
            purpose=Payment.Purpose.PRO_SUBSCRIPTION,
            provider_transaction_id="7777",
            metadata={
                "plan_id": self.plan.id,
                "plan_snapshot": {
                    "name": self.plan.name,
                    "duration_days": self.plan.duration_days,
                    "price": str(self.plan.price),
                },
            },
        )

        resp = self.client.post(
            "/api/v1/payments/atmos/pay/confirm/",
            {"payment_id": payment.id, "otp": "5555"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "success")

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.COMPLETED)
        self.assertEqual(payment.metadata.get("ofd_url"), "https://ofd.example/check/123")
        from django.utils import timezone

        self.assertTrue(
            ProSubscription.objects.filter(
                user=self.user, expires_at__gt=timezone.now()
            ).exists()
        )

    @patch("app.payments.atmos_views.atmos_client.pay_apply")
    def test_confirm_idempotent_if_already_completed(self, mock_apply):
        payment = Payment.objects.create(
            user=self.user,
            amount=self.plan.price,
            provider=Payment.Provider.ATMOS,
            purpose=Payment.Purpose.PRO_SUBSCRIPTION,
            provider_transaction_id="7777",
            status=Payment.Status.COMPLETED,
            metadata={"ofd_url": "https://ofd.example/check/old"},
        )

        resp = self.client.post(
            "/api/v1/payments/atmos/pay/confirm/",
            {"payment_id": payment.id, "otp": "5555"},
            format="json",
        )

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "completed")
        mock_apply.assert_not_called()


@override_settings(ATMOS=ATMOS_TEST_SETTINGS)
class AtmosWebhookTests(BaseAPITestCase):
    """Atmos callback (`/payments/webhook/atmos/`) — sign (MD5) tekshiruvi.

    Atmos docs (Callback API): webhook body field'lari:
      store_id, transaction_id, transaction_time, amount, account, sign
    sign = MD5(store_id + transaction_id + account + amount + api_key)
    (docs `invoice` desa-da, amalda `account` keladi — verify_webhook).
    """

    URL = "/api/v1/payments/webhook/atmos/"
    API_KEY = "test_webhook_api_key"
    STORE_ID = "10869"

    def setUp(self):
        super().setUp()
        self.user = self.create_patient(phone="998904444444")
        self.plan = ProPlan.objects.create(
            name="1 oy", duration_days=30, price=Decimal("50000.00")
        )
        self.payment = Payment.objects.create(
            user=self.user,
            amount=Decimal("50000.00"),
            provider=Payment.Provider.ATMOS,
            purpose=Payment.Purpose.PRO_SUBSCRIPTION,
            provider_transaction_id="7777",
            metadata={
                "plan_id": self.plan.id,
                "plan_snapshot": {
                    "name": self.plan.name,
                    "duration_days": self.plan.duration_days,
                    "price": str(self.plan.price),
                },
            },
        )
        # atmos_client singleton settings.ATMOS ni import paytida o'qiydi —
        # override_settings'dan keyin instance attributes'ni manual yangilaymiz.
        self._patcher_key = patch(
            "app.payments.atmos_views.atmos_client.api_key", self.API_KEY
        )
        self._patcher_store = patch(
            "app.payments.atmos_views.atmos_client.store_id", self.STORE_ID
        )
        self._patcher_key.start()
        self._patcher_store.start()
        self.addCleanup(self._patcher_key.stop)
        self.addCleanup(self._patcher_store.stop)

    def _body(self, **overrides):
        body = {
            "store_id": self.STORE_ID,
            "transaction_id": 7777,
            "transaction_time": "2026-05-15 12:00:00",
            "account": str(self.payment.id),
            "amount": 5_000_000,
        }
        body.update(overrides)
        body.setdefault(
            "sign",
            _make_sign(
                body["store_id"],
                body["transaction_id"],
                body["account"],
                body["amount"],
                self.API_KEY,
            ),
        )
        return body

    def test_rejects_invalid_sign(self):
        resp = self.client.post(
            self.URL, self._body(sign="0" * 32), format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_rejects_missing_sign(self):
        body = self._body()
        body.pop("sign")
        resp = self.client.post(self.URL, body, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_valid_sign_completes_payment(self):
        resp = self.client.post(self.URL, self._body(), format="json")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], 1)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.COMPLETED)

        from django.utils import timezone

        self.assertTrue(
            ProSubscription.objects.filter(
                user=self.user, expires_at__gt=timezone.now()
            ).exists()
        )

    def test_amount_mismatch_returns_400(self):
        resp = self.client.post(
            self.URL, self._body(amount=1_000_000), format="json"
        )

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_idempotent_on_repeat(self):
        """Webhook ikki marta kelsa, ProSubscription bittadan oshmaydi."""
        self.client.post(self.URL, self._body(), format="json")
        self.client.post(self.URL, self._body(), format="json")

        self.assertEqual(
            ProSubscription.objects.filter(user=self.user).count(), 1
        )

    def test_payment_not_found_returns_404(self):
        resp = self.client.post(
            self.URL, self._body(account="999999"), format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_sign_includes_api_key_secret(self):
        """Agar attaker api_key bilmasa, to'g'ri sign ololmaydi."""
        body = self._body()
        # api_key'siz hisoblangan sign
        bad_sign = hashlib.md5(
            f"{body['store_id']}{body['transaction_id']}{body['account']}{body['amount']}".encode()
        ).hexdigest()
        body["sign"] = bad_sign

        resp = self.client.post(self.URL, body, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
