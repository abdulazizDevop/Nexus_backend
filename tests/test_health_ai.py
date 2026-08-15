from unittest.mock import patch

from rest_framework import status

from app.doctors.models import DoctorPatient, DoctorProfile, Specialty
from app.health_ai.models import AiConversation, AiMessage
from tests.base import BaseAPITestCase


class HealthAIAccessTests(BaseAPITestCase):
    """Health AI — doctor-only access + chat oqimi."""

    def setUp(self):
        super().setUp()
        self.specialty = Specialty.objects.create(name="Terapevt")
        self.doctor_user = self.create_doctor()
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user, specialty=self.specialty
        )
        self.patient = self.create_patient()
        DoctorPatient.objects.create(
            doctor=self.profile,
            patient=self.patient,
            status=DoctorPatient.Status.ACCEPTED,
            added_by=DoctorPatient.AddedBy.DOCTOR,
        )

    # --- Permission ---

    def test_patient_cannot_access_reports(self):
        """GET /health-ai/reports/ — patient 403 (doctor-only tool)"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/health-ai/reports/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_patient_cannot_access_chat(self):
        """GET /health-ai/chat/conversations/ — patient 403"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/health-ai/chat/conversations/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_doctor_reports_empty(self):
        """GET /health-ai/reports/ — doctor 200, bo'sh"""
        self.authenticate(self.doctor_user)
        resp = self.client.get("/api/v1/health-ai/reports/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["results"], [])

    # --- Chat conversation access control ---

    def test_create_conversation_connected(self):
        """POST /health-ai/chat/conversations/ — bog'langan bemorga 201"""
        self.authenticate(self.doctor_user)
        resp = self.client.post(
            "/api/v1/health-ai/chat/conversations/", {"patient_id": self.patient.id}
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertTrue(AiConversation.objects.filter(id=resp.data["id"]).exists())

    def test_create_conversation_not_connected(self):
        """POST — bog'lanmagan bemorga 404"""
        other_patient = self.create_patient()
        self.authenticate(self.doctor_user)
        resp = self.client.post(
            "/api/v1/health-ai/chat/conversations/", {"patient_id": other_patient.id}
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # --- Chat send (Gemini mock) ---

    @patch(
        "app.health_ai.views.generate_text",
        return_value={"text": "Bemor ko'rsatkichlari barqaror.", "tokens_input": 12, "tokens_output": 8},
    )
    def test_chat_send_saves_user_and_assistant(self, mock_gen):
        """POST messages — user + assistant xabar atomik saqlanadi, AI javob qaytadi"""
        self.authenticate(self.doctor_user)
        convo = AiConversation.objects.create(
            doctor_profile=self.profile, patient=self.patient, language="uz"
        )
        resp = self.client.post(
            f"/api/v1/health-ai/chat/conversations/{convo.id}/messages/",
            {"content": "Bu bemorda nimaga e'tibor berishim kerak?"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["role"], "assistant")
        self.assertIn("barqaror", resp.data["content"])
        # user + assistant = 2 ta xabar
        self.assertEqual(AiMessage.objects.filter(conversation=convo).count(), 2)
        mock_gen.assert_called_once()
        # title avto-generatsiya (birinchi savoldan)
        convo.refresh_from_db()
        self.assertTrue(convo.title)

    def test_chat_send_other_doctor_forbidden(self):
        """POST messages — boshqa doctor suhbatiga kira olmaydi (404)"""
        convo = AiConversation.objects.create(
            doctor_profile=self.profile, patient=self.patient, language="uz"
        )
        other_doc = self.create_doctor()
        DoctorProfile.objects.create(user=other_doc, specialty=self.specialty)
        self.authenticate(other_doc)
        resp = self.client.post(
            f"/api/v1/health-ai/chat/conversations/{convo.id}/messages/",
            {"content": "test"},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
