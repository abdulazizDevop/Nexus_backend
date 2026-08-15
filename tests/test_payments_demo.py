"""To'lov demo-rejimi (PAYMENTS_ENABLED=False) testlari."""

from django.test import override_settings
from rest_framework import status

from tests.base import BaseAPITestCase


class PaymentsDemoModeTests(BaseAPITestCase):
    """Demo rejimda to'lov yozuv endpointlari 503, o'qish ishlaydi"""

    def test_subscribe_returns_demo_response(self):
        """POST /payments/pro/subscribe/ — 503 + demo xabari"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/payments/pro/subscribe/", {"plan_id": 1}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.json()["code"], "payments_demo_mode")
        self.assertIn("demo", resp.json()["detail"])

    def test_tariff_purchase_returns_demo_response(self):
        """POST /payments/doctor-tariffs/{id}/purchase/ — 503 + demo xabari"""
        self.auth_as_patient()
        resp = self.client.post("/api/v1/payments/doctor-tariffs/1/purchase/")
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.json()["code"], "payments_demo_mode")

    def test_webhook_blocked_in_demo(self):
        """POST /payments/webhook/payme/ — demo rejimda qabul qilinmaydi"""
        resp = self.client.post("/api/v1/payments/webhook/payme/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_read_endpoints_still_work(self):
        """GET /payments/pro/plans/ — o'qish demo rejimda ham ishlaydi"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/payments/pro/plans/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    @override_settings(PAYMENTS_ENABLED=True)
    def test_flag_on_disables_demo_block(self):
        """PAYMENTS_ENABLED=True — middleware to'sqinlik qilmaydi"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/payments/pro/subscribe/", {"plan_id": 999}, format="json"
        )
        # Endi so'rov view'ga yetadi (plan topilmaydi — 503 EMAS)
        self.assertNotEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
