"""AI Navigator (ai_navigator_api_contract.md) testlari — Gemini mock bilan."""

from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework import status

from app.medical.models import MedicalCondition, RoadmapStep
from tests.base import BaseAPITestCase

_ROADMAP_PARSED = {
    "plain_explanation": "Oshqozon kislotasi qizilo'ngachga qaytib chiqadi.",
    "what_to_watch": ["Achishish kuchaysa", "Yutishda og'riq"],
    "red_flags": [
        {"text": "Qon aralash qusish", "action": "Zudlik bilan 103", "severity": "emergency"}
    ],
    "steps": [
        {
            "order": 1, "type": "education", "title": "Kasallik haqida tushuncha",
            "description": "GERD nima.", "body": "To'liq matn.", "due_in_days": 0,
            "medication_name": "", "dosage": "", "times_per_day": 0, "daily_times": [],
            "duration_days": 0, "notes": "", "analysis_type": "", "preparation": "",
            "specialty": "", "reason": "",
        },
        {
            "order": 2, "type": "analysis", "title": "Umumiy qon tahlili",
            "description": "Kamqonlikni tekshirish.", "body": "", "due_in_days": 5,
            "medication_name": "", "dosage": "", "times_per_day": 0, "daily_times": [],
            "duration_days": 0, "notes": "", "analysis_type": "blood_general",
            "preparation": "Nahorga", "specialty": "", "reason": "",
        },
        {
            "order": 3, "type": "consultation", "title": "Gastroenterolog nazorati",
            "description": "Natijalar bilan ko'rik.", "body": "", "due_in_days": 20,
            "medication_name": "", "dosage": "", "times_per_day": 0, "daily_times": [],
            "duration_days": 0, "notes": "", "analysis_type": "", "preparation": "",
            "specialty": "gastroenterolog", "reason": "Natijani baholash",
        },
    ],
    "tokens_input": 10, "tokens_output": 20,
}

_FROM_IMAGE_PARSED = {
    **_ROADMAP_PARSED,
    "is_medical_document": True,
    "confidence": 0.86,
    "recognized_text": "Tashxis: Surunkali gastrit ...",
    "diagnosis_title": "Surunkali gastrit",
    "icd10": "K29.5",
    "needs_review": False,
}


class NavigatorDiagnosisTests(BaseAPITestCase):
    """Manual kiritish + ro'yxat + detail (kontrakt §1, §2, §5)"""

    @patch("app.navigator.ai.generate_roadmap", return_value=dict(_ROADMAP_PARSED))
    def test_create_manual_builds_roadmap(self, _mock):
        """POST /navigator/diagnoses/ — AI roadmap quradi, 1-qadam current"""
        me = self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/navigator/diagnoses/",
            {"title": "Surunkali gastrit", "icd10": None, "diagnosed_at": "2026-08-01"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["title"], "Surunkali gastrit")
        self.assertEqual(resp.data["source"], "manual")
        self.assertTrue(resp.data["is_active"])
        self.assertEqual(len(resp.data["what_to_watch"]), 2)
        steps = resp.data["roadmap"]["steps"]
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0]["status"], "current")
        self.assertEqual(steps[1]["status"], "locked")
        self.assertEqual(steps[1]["payload"]["analysis_type"], "blood_general")
        self.assertEqual(
            MedicalCondition.objects.get(user=me, is_active=True).source, "manual"
        )

    @patch("app.navigator.ai.generate_roadmap", return_value=dict(_ROADMAP_PARSED))
    def test_second_diagnosis_deactivates_first(self, _mock):
        """Yangi tashxis — avvalgisi deaktiv"""
        self.auth_as_patient()
        self.client.post(
            "/api/v1/navigator/diagnoses/", {"title": "Birinchi"}, format="json"
        )
        self.client.post(
            "/api/v1/navigator/diagnoses/", {"title": "Ikkinchi"}, format="json"
        )
        self.assertEqual(MedicalCondition.objects.filter(is_active=True).count(), 1)
        self.assertEqual(
            MedicalCondition.objects.get(is_active=True).name, "Ikkinchi"
        )

    @patch("app.navigator.ai.generate_roadmap", return_value=dict(_ROADMAP_PARSED))
    def test_list_paginated(self, _mock):
        """GET /navigator/diagnoses/ — paginatsiyalangan ro'yxat"""
        self.auth_as_patient()
        self.client.post(
            "/api/v1/navigator/diagnoses/", {"title": "GERD"}, format="json"
        )
        resp = self.client.get("/api/v1/navigator/diagnoses/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        row = resp.data["results"][0]
        self.assertEqual(row["roadmap_progress"]["total_steps"], 3)
        self.assertIn("doctor", row)

    @patch("app.navigator.ai.generate_roadmap", return_value=None)
    def test_ai_error_503(self, _mock):
        """AI ishlamasa — 503 ai_unavailable, tashxis yaratilmaydi"""
        me = self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/navigator/diagnoses/", {"title": "X"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.data["detail"], "ai_unavailable")
        self.assertFalse(MedicalCondition.objects.filter(user=me).exists())


class NavigatorActiveAndCompleteTests(BaseAPITestCase):
    """Aktiv roadmap + qadam bajarish (kontrakt §3, §6)"""

    def _create(self):
        with patch(
            "app.navigator.ai.generate_roadmap", return_value=dict(_ROADMAP_PARSED)
        ):
            return self.client.post(
                "/api/v1/navigator/diagnoses/", {"title": "GERD"}, format="json"
            ).data

    def test_active_null_when_empty(self):
        """Aktiv tashxis yo'q — {"diagnosis": null} (200)"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/navigator/roadmap/active/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["diagnosis"])

    def test_active_returns_full_object(self):
        """Aktiv roadmap §2 strukturasida qaytadi"""
        self.auth_as_patient()
        created = self._create()
        resp = self.client.get("/api/v1/navigator/roadmap/active/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], created["id"])
        self.assertEqual(resp.data["roadmap"]["total_steps"], 3)

    def test_complete_unlocks_next(self):
        """POST steps/{id}/complete/ — done + keyingisi current"""
        me = self.auth_as_patient()
        self._create()
        first = RoadmapStep.objects.get(user=me, order=1)
        second = RoadmapStep.objects.get(user=me, order=2)
        resp = self.client.post(f"/api/v1/navigator/steps/{first.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["step"]["status"], "done")
        self.assertEqual(resp.data["roadmap_progress"]["done_steps"], 1)
        self.assertEqual(resp.data["unlocked_step_ids"], [second.id])
        second.refresh_from_db()
        self.assertEqual(second.status, "current")

    def test_complete_foreign_step_404(self):
        """Boshqa bemor qadami — 404"""
        self.auth_as_patient()
        self._create()
        step_id = RoadmapStep.objects.first().id
        self.auth_as_patient(phone="998901230001")
        resp = self.client.post(f"/api/v1/navigator/steps/{step_id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class NavigatorFromImageTests(BaseAPITestCase):
    """Rasmdan tashxis (kontrakt §4)"""

    @patch(
        "app.navigator.ai.extract_and_build_from_image",
        return_value=dict(_FROM_IMAGE_PARSED),
    )
    def test_from_image_creates_diagnosis(self, _mock):
        """201 — source=document + extraction bloki"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/navigator/diagnoses/from-image/",
            {"image": SimpleUploadedFile("dx.jpg", b"fake", content_type="image/jpeg")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["source"], "document")
        self.assertEqual(resp.data["title"], "Surunkali gastrit")
        self.assertEqual(resp.data["extraction"]["confidence"], 0.86)
        self.assertFalse(resp.data["extraction"]["needs_review"])

    @patch(
        "app.navigator.ai.extract_and_build_from_image",
        return_value={**_FROM_IMAGE_PARSED, "is_medical_document": False},
    )
    def test_from_image_unreadable_422(self, _mock):
        """Tibbiy hujjat emas — 422 document_unreadable"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/navigator/diagnoses/from-image/",
            {"image": SimpleUploadedFile("x.jpg", b"fake", content_type="image/jpeg")},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.data["detail"], "document_unreadable")


class NavigatorTriageChatTests(BaseAPITestCase):
    """Triaj + AI chat (kontrakt §7, §8)"""

    @patch(
        "app.navigator.ai.triage",
        return_value={
            "urgency": "routine",
            "summary": "GERD tashxisiga mos belgi.",
            "advice": ["Ovqatdan keyin darhol yotmang"],
            "recommended_specialties": [
                {"code": "gastroenterolog", "label": "Gastroenterolog", "reason": "Asosiy tashxis"}
            ],
            "disclaimer": "Bu tashxis emas.",
            "tokens_input": 5, "tokens_output": 5,
        },
    )
    def test_triage(self, _mock):
        """POST /navigator/triage/ — urgency + mutaxassisliklar"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/navigator/triage/",
            {"complaint": "Ko'krak orqasida achishish"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["urgency"], "routine")
        self.assertEqual(
            resp.data["recommended_specialties"][0]["code"], "gastroenterolog"
        )
        self.assertIn("recommended_doctors", resp.data)
        self.assertIn("disclaimer", resp.data)

    @patch(
        "app.navigator.ai.chat_reply",
        return_value={
            "reply": "Omeprazol nahorga ichiladi.",
            "related_step_ids": [],
            "needs_doctor": False,
            "disclaimer": "",
            "tokens_input": 5, "tokens_output": 5,
        },
    )
    def test_chat_creates_conversation(self, _mock):
        """POST /navigator/chat/ — conversation_id "c-N" qaytadi"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/navigator/chat/",
            {"message": "Omeprazolni qachon ichaman?"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertTrue(resp.data["conversation_id"].startswith("c-"))
        self.assertIn("Omeprazol", resp.data["reply"])
        self.assertIsNone(resp.data["disclaimer"])

        # Xuddi shu suhbatda davom etish
        resp2 = self.client.post(
            "/api/v1/navigator/chat/",
            {"message": "Rahmat", "conversation_id": resp.data["conversation_id"]},
            format="json",
        )
        self.assertEqual(resp2.data["conversation_id"], resp.data["conversation_id"])

    def test_chat_daily_limit(self):
        """Kunlik limit tugasa — 429 daily_limit_exceeded"""
        me = self.auth_as_patient()
        cache.set(
            f"navchat:{me.id}:{timezone.localdate().isoformat()}", 30, 3600
        )
        resp = self.client.post(
            "/api/v1/navigator/chat/", {"message": "Salom"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(resp.data["detail"], "daily_limit_exceeded")
