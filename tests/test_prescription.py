"""Retsept skan (AI) oqimi testlari — Gemini va S3 mock bilan."""

import json
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from app.treatment.models import PrescriptionScan, Treatment
from tests.base import BaseAPITestCase

_AI_PARSED = {
    "is_prescription": True,
    "summary": "Qog'ozda 2 ta dori va ichish tartibi yozilgan.",
    "items": [
        {
            "title": "Amlodipin 5mg",
            "type": "medication",
            "dosage": "1 tabletka",
            "times": ["08:00"],
            "repeat": "daily",
            "duration_days": 30,
            "notes": "Ertalab, ovqatdan keyin",
            "source_text": "Amlodipin 5mg 1x1 ertalab",
        },
        {
            "title": "Magniy B6",
            "type": "medication",
            "dosage": "",
            "times": ["08:00", "20:00"],
            "repeat": "daily",
            "duration_days": 0,
            "notes": "",
            "source_text": "Magniy B6 kuniga 2 mahal",
        },
    ],
    "warnings": ["'kuniga 2 mahal' 08:00/20:00 deb taqsimlandi."],
}
_GEMINI_OK = {
    "text": json.dumps(_AI_PARSED),
    "tokens_input": 100,
    "tokens_output": 50,
}
_S3_HEAD = {"size": 1024, "content_type": "image/jpeg"}
_S3_BYTES = (b"fake-image-bytes", "image/jpeg")


def _mock_s3(fn):
    """head_object_or_none + download_file_bytes mocklarini bitta dekoratorda."""
    fn = patch(
        "app.treatment.views.prescription.head_object_or_none", return_value=_S3_HEAD
    )(fn)
    fn = patch(
        "app.treatment.views.prescription.download_file_bytes", return_value=_S3_BYTES
    )(fn)
    return fn


class PrescriptionUploadTests(BaseAPITestCase):
    """Upload URL olish"""

    def test_upload_url_own_prefix(self):
        """POST upload-url/ — image_key o'z prefiksida bo'ladi"""
        me = self.auth_as_patient()
        with patch(
            "app.treatment.views.prescription.generate_upload_url",
            return_value="https://s3.example/put",
        ):
            resp = self.client.post(
                "/api/v1/treatments/prescription/upload-url/",
                {"file_type": "image/jpeg"},
                format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data["image_key"].startswith(f"prescriptions/{me.id}/"))
        self.assertIn("upload_url", resp.data)


class PrescriptionAnalyzeTests(BaseAPITestCase):
    """AI tahlil bosqichi"""

    @_mock_s3
    @patch("app.treatment.prescription_ai.generate_with_image", return_value=_GEMINI_OK)
    def test_analyze_creates_pending_scan(self, *mocks):
        """POST analyze/ — pending_review scan + AI takliflar qaytadi"""
        me = self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/prescription/analyze/",
            {"image_key": f"prescriptions/{me.id}/abc123.jpg"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["status"], "pending_review")
        self.assertEqual(len(resp.data["ai_items"]), 2)
        self.assertEqual(resp.data["ai_items"][0]["title"], "Amlodipin 5mg")
        # Hech qanday Treatment hali yaratilmagan
        self.assertEqual(Treatment.objects.filter(user=me).count(), 0)

    def test_analyze_foreign_image_key_rejected(self):
        """POST analyze/ — boshqa user prefiksi (IDOR) → 400"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/prescription/analyze/",
            {"image_key": "prescriptions/99999/abc123.jpg"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @_mock_s3
    @patch(
        "app.treatment.prescription_ai.generate_with_image",
        return_value={
            "text": json.dumps(
                {"is_prescription": False, "summary": "", "items": [], "warnings": []}
            ),
            "tokens_input": 1,
            "tokens_output": 1,
        },
    )
    def test_analyze_not_a_prescription(self, *mocks):
        """Retsept bo'lmagan rasm → 400, scan yaratilmaydi"""
        me = self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/prescription/analyze/",
            {"image_key": f"prescriptions/{me.id}/xyz.jpg"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PrescriptionScan.objects.filter(user=me).exists())


class PrescriptionConfirmTests(BaseAPITestCase):
    """Tasdiqlash / rad etish"""

    def _pending_scan(self, user):
        return PrescriptionScan.objects.create(
            user=user,
            image_key=f"prescriptions/{user.id}/abc.jpg",
            summary="Test",
            ai_items=_AI_PARSED["items"],
            ai_warnings=_AI_PARSED["warnings"],
        )

    def test_confirm_creates_treatments(self):
        """POST confirm/ — itemlar Treatment bo'ladi, scan confirmed"""
        me = self.auth_as_patient()
        scan = self._pending_scan(me)
        resp = self.client.post(
            f"/api/v1/treatments/prescription/{scan.id}/confirm/",
            {
                "items": [
                    {
                        "title": "Amlodipin 5mg",
                        "type": "medication",
                        "dosage": "1 tabletka",
                        "times": ["08:00"],
                        "repeat": "daily",
                        "duration_days": 30,
                        "notes": "Ertalab",
                    },
                    {
                        "title": "Magniy B6",
                        "times": ["08:00", "20:00"],
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(len(resp.data["created_treatments"]), 2)

        scan.refresh_from_db()
        self.assertEqual(scan.status, PrescriptionScan.Status.CONFIRMED)
        self.assertEqual(len(scan.created_treatment_ids), 2)

        t1 = Treatment.objects.get(title="Amlodipin 5mg")
        self.assertEqual(t1.times, ["08:00"])
        self.assertEqual(t1.dosage, "1 tabletka")
        self.assertIsNone(t1.created_by)  # self-added
        self.assertEqual(
            t1.end_date, timezone.localdate() + timezone.timedelta(days=30)
        )
        t2 = Treatment.objects.get(title="Magniy B6")
        self.assertEqual(t2.times, ["08:00", "20:00"])
        self.assertIsNone(t2.end_date)

    def test_confirm_twice_rejected(self):
        """Ikkinchi confirm — 400"""
        me = self.auth_as_patient()
        scan = self._pending_scan(me)
        body = {"items": [{"title": "X"}]}
        self.client.post(
            f"/api/v1/treatments/prescription/{scan.id}/confirm/", body, format="json"
        )
        resp = self.client.post(
            f"/api/v1/treatments/prescription/{scan.id}/confirm/", body, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_discard(self):
        """POST discard/ — scan discarded, Treatment yaratilmaydi"""
        me = self.auth_as_patient()
        scan = self._pending_scan(me)
        resp = self.client.post(f"/api/v1/treatments/prescription/{scan.id}/discard/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        scan.refresh_from_db()
        self.assertEqual(scan.status, PrescriptionScan.Status.DISCARDED)
        self.assertEqual(Treatment.objects.filter(user=me).count(), 0)

    def test_other_users_scan_not_found(self):
        """Boshqa user skanini tasdiqlab bo'lmaydi (404)"""
        other = self.create_patient(phone="998909990001")
        scan = self._pending_scan(other)
        self.auth_as_patient()
        resp = self.client.post(
            f"/api/v1/treatments/prescription/{scan.id}/confirm/",
            {"items": [{"title": "X"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
