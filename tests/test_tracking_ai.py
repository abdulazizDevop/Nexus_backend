"""Tracking AI — bemor-markazli AI kuzatuv testlari."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from app.doctors.models import DoctorPatient, DoctorProfile, Specialty
from app.family.models import FamilyLink
from app.tracking_ai.models import AITrackingReport
from tests.base import BaseAPITestCase

_AI_JSON = json.dumps(
    {
        "summary": "Bugun muolajalar to'liq bajarildi, ko'rsatkichlar barqaror.",
        "detected_changes": [
            {"title": "Muolaja intizomi", "description": "100% bajarildi", "severity": "info"}
        ],
        "recommendations": ["Suv ichishni unutmang."],
        "severity": "normal",
    }
)
_AI_OK = {"text": _AI_JSON, "tokens_input": 10, "tokens_output": 20}


class TrackingReportAccessTests(BaseAPITestCase):
    """Hisobotga kirish: bemor / shifokor / oila a'zosi / begona"""

    def _report_for(self, patient, day=None):
        day = day or timezone.localdate()
        return AITrackingReport.objects.create(
            patient=patient,
            period_start=day,
            period_end=day,
            summary="Test xulosa",
            severity=AITrackingReport.Severity.NORMAL,
        )

    def test_patient_lists_own_reports(self):
        """GET /tracking-ai/reports/ — bemor faqat o'zinikini ko'radi"""
        me = self.auth_as_patient()
        other = self.create_patient(phone="998908880001")
        self._report_for(me)
        self._report_for(other)
        resp = self.client.get("/api/v1/tracking-ai/reports/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)

    def test_latest_and_seen(self):
        """GET latest/ + POST {id}/seen/"""
        me = self.auth_as_patient()
        old = self._report_for(me, timezone.localdate() - timedelta(days=1))
        new = self._report_for(me)
        resp = self.client.get("/api/v1/tracking-ai/reports/latest/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], new.id)

        resp = self.client.post(f"/api/v1/tracking-ai/reports/{old.id}/seen/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        old.refresh_from_db()
        self.assertIsNotNone(old.seen_at)

    def test_accepted_doctor_reads_patient_reports(self):
        """GET by-patient/{id}/ — ACCEPTED shifokor o'qiy oladi"""
        patient = self.create_patient(phone="998908880002")
        self._report_for(patient)
        doctor = self.auth_as_doctor()
        profile = DoctorProfile.objects.create(
            user=doctor, specialty=Specialty.objects.create(name="Terapevt")
        )
        DoctorPatient.objects.create(
            doctor=profile,
            patient=patient,
            status=DoctorPatient.Status.ACCEPTED,
        )
        resp = self.client.get(f"/api/v1/tracking-ai/reports/by-patient/{patient.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["count"], 1)

    def test_accepted_family_member_reads_patient_reports(self):
        """GET by-patient/{id}/ — ACCEPTED oila a'zosi o'qiy oladi"""
        patient = self.create_patient(phone="998908880003")
        self._report_for(patient)
        member = self.auth_as_patient()
        FamilyLink.objects.create(
            patient=patient, member=member, status=FamilyLink.Status.ACCEPTED
        )
        resp = self.client.get(f"/api/v1/tracking-ai/reports/by-patient/{patient.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["count"], 1)

    def test_stranger_forbidden(self):
        """GET by-patient/{id}/ — bog'lanmagan user uchun 403"""
        patient = self.create_patient(phone="998908880004")
        self._report_for(patient)
        self.auth_as_patient()
        resp = self.client.get(f"/api/v1/tracking-ai/reports/by-patient/{patient.id}/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TrackingGenerateTests(BaseAPITestCase):
    """On-demand hisobot yaratish (Gemini mock bilan)"""

    @patch("services.gemini.generate_text", return_value=_AI_OK)
    def test_generate_creates_report(self, _mock):
        """POST /tracking-ai/reports/generate/ — hisobot yaratiladi va saqlanadi"""
        me = self.auth_as_patient()
        resp = self.client.post("/api/v1/tracking-ai/reports/generate/")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["severity"], "normal")
        self.assertTrue(
            AITrackingReport.objects.filter(
                patient=me, period_start=timezone.localdate()
            ).exists()
        )

    @patch("services.gemini.generate_text", return_value=_AI_OK)
    def test_generate_is_idempotent_upsert(self, _mock):
        """Ikki marta generate — bitta qator (upsert)"""
        me = self.auth_as_patient()
        self.client.post("/api/v1/tracking-ai/reports/generate/")
        self.client.post("/api/v1/tracking-ai/reports/generate/")
        self.assertEqual(
            AITrackingReport.objects.filter(
                patient=me, period_start=timezone.localdate()
            ).count(),
            1,
        )

    @patch("services.gemini.generate_text", return_value={"error": "AI xizmati vaqtincha ishlamayapti"})
    def test_generate_ai_error_returns_502(self, _mock):
        """Gemini xatosi — 502 va qator yaratilmaydi"""
        me = self.auth_as_patient()
        resp = self.client.post("/api/v1/tracking-ai/reports/generate/")
        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(AITrackingReport.objects.filter(patient=me).exists())
