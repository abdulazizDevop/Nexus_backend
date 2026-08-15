"""Navigator yo'l xaritasi (roadmap) testlari."""

from rest_framework import status

from app.medical.models import MedicalCondition, RoadmapStep
from tests.base import BaseAPITestCase

_SETUP_BODY = {
    "condition": {
        "name": "Arterial gipertoniya",
        "icd10": "I10",
        "plain_explanation": "Qon bosimining doimiy yuqori bo'lishi.",
        "type": "chronic",
    },
    "steps": [
        {"period": "first_week", "order": 1, "title": "Kardiolog qabuliga yoziling",
         "specialist": "Kardiolog", "description": "Bosim yozuvlarini olib boring."},
        {"period": "first_week", "order": 2, "title": "Asosiy tahlillarni topshiring",
         "specialist": "Laboratoriya"},
        {"period": "first_month", "order": 1, "title": "EKG va exokardiografiya",
         "specialist": "Kardiolog"},
        {"period": "ongoing", "order": 1, "title": "Kunlik bosim nazorati"},
    ],
}


class RoadmapSetupTests(BaseAPITestCase):
    """Setup — tashxis + qadamlar bitta so'rovda"""

    def test_setup_creates_condition_and_steps(self):
        """POST roadmap/setup/ — aktiv tashxis + qadamlar yaratiladi"""
        me = self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/medical/roadmap/setup/", _SETUP_BODY, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["condition"]["name"], "Arterial gipertoniya")
        self.assertEqual(resp.data["condition"]["icd10"], "I10")
        self.assertTrue(resp.data["condition"]["is_active"])
        self.assertEqual(resp.data["progress"], {
            "completed": 0, "total": 3, "percent": 0, "habits": 1,
        })
        self.assertEqual(RoadmapStep.objects.filter(user=me).count(), 4)

    def test_setup_deactivates_previous_condition(self):
        """Ikkinchi setup — avvalgi tashxis deaktiv bo'ladi"""
        self.auth_as_patient()
        self.client.post("/api/v1/medical/roadmap/setup/", _SETUP_BODY, format="json")
        body2 = dict(_SETUP_BODY, condition={"name": "Qandli diabet", "type": "chronic"})
        resp = self.client.post("/api/v1/medical/roadmap/setup/", body2, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            MedicalCondition.objects.filter(is_active=True).count(), 1
        )
        self.assertEqual(
            MedicalCondition.objects.get(is_active=True).name, "Qandli diabet"
        )


class RoadmapActiveTests(BaseAPITestCase):
    """Aktiv yo'l xaritasi + progress"""

    def test_active_returns_grouped_steps(self):
        """GET roadmap/active/ — davrlar bo'yicha guruhlangan qadamlar"""
        self.auth_as_patient()
        self.client.post("/api/v1/medical/roadmap/setup/", _SETUP_BODY, format="json")
        resp = self.client.get("/api/v1/medical/roadmap/active/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        periods = {p["period"]: len(p["steps"]) for p in resp.data["periods"]}
        self.assertEqual(periods, {"first_week": 2, "first_month": 1, "ongoing": 1})

    def test_active_404_when_no_condition(self):
        """Aktiv tashxis yo'q — 404"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/medical/roadmap/active/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class RoadmapCompleteTests(BaseAPITestCase):
    """Qadam bajarish / bekor qilish"""

    def _setup(self):
        me = self.auth_as_patient()
        self.client.post("/api/v1/medical/roadmap/setup/", _SETUP_BODY, format="json")
        return me

    def test_complete_updates_progress(self):
        """POST steps/{id}/complete/ — progress yangilanadi, idempotent"""
        me = self._setup()
        step = RoadmapStep.objects.filter(
            user=me, period=RoadmapStep.Period.FIRST_WEEK
        ).first()
        resp = self.client.post(f"/api/v1/medical/roadmap/steps/{step.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["step"]["status"], "completed")
        self.assertEqual(resp.data["progress"]["completed"], 1)
        self.assertEqual(resp.data["progress"]["percent"], 33)
        # Idempotent
        resp = self.client.post(f"/api/v1/medical/roadmap/steps/{step.id}/complete/")
        self.assertEqual(resp.data["progress"]["completed"], 1)

    def test_habit_step_cannot_complete(self):
        """Doimiy (odat) qadam — complete 400"""
        me = self._setup()
        habit = RoadmapStep.objects.get(user=me, period=RoadmapStep.Period.ONGOING)
        resp = self.client.post(f"/api/v1/medical/roadmap/steps/{habit.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_uncomplete(self):
        """POST steps/{id}/uncomplete/ — belgini olib tashlaydi"""
        me = self._setup()
        step = RoadmapStep.objects.filter(
            user=me, period=RoadmapStep.Period.FIRST_WEEK
        ).first()
        self.client.post(f"/api/v1/medical/roadmap/steps/{step.id}/complete/")
        resp = self.client.post(f"/api/v1/medical/roadmap/steps/{step.id}/uncomplete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["step"]["status"], "pending")
        self.assertEqual(resp.data["progress"]["completed"], 0)

    def test_other_users_step_404(self):
        """Boshqa bemor qadamini belgilab bo'lmaydi"""
        other_me = self._setup()
        step = RoadmapStep.objects.filter(user=other_me).first()
        self.auth_as_patient(phone="998901234599")
        resp = self.client.post(f"/api/v1/medical/roadmap/steps/{step.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
