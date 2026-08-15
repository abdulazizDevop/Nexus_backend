from datetime import timedelta

from rest_framework import status
from django.utils import timezone

from app.treatment.models import Treatment, TreatmentLog
from tests.base import BaseAPITestCase


class TreatmentCRUDTests(BaseAPITestCase):
    """Treatment — CRUD endpointlar"""

    def test_create_treatment(self):
        """POST /treatments/ — muolaja yaratish"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/",
            {
                "type": "medication",
                "title": "Amoksisilin",
                "dosage": "500mg",
                "time": "08:00",
                "repeat": "daily",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "active")

    def test_create_treatment_with_interval(self):
        """POST /treatments/ — interval_hours bilan"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/",
            {
                "type": "medication",
                "title": "Paratsetamol",
                "time": "08:00",
                "end_time": "20:00",
                "interval_hours": 4,
                "repeat": "daily",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("scheduled_times", resp.data)
        self.assertEqual(len(resp.data["scheduled_times"]), 4)  # 08,12,16,20

    def test_create_treatment_custom_days(self):
        """POST /treatments/ — custom kunlar"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/",
            {
                "type": "exercise",
                "title": "Yurish",
                "time": "07:00",
                "repeat": "custom",
                "custom_days": "1,3,5",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_custom_without_days_fails(self):
        """POST /treatments/ — repeat=custom lekin custom_days yo'q"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/",
            {
                "type": "exercise",
                "title": "Yurish",
                "time": "07:00",
                "repeat": "custom",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_interval_without_end_time_fails(self):
        """POST /treatments/ — interval_hours lekin end_time yo'q"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/",
            {
                "type": "medication",
                "title": "Test",
                "time": "08:00",
                "interval_hours": 2,
                "repeat": "daily",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_treatments(self):
        """GET /treatments/ — faqat o'z muolajalarini ko'radi"""
        user = self.auth_as_patient()
        Treatment.objects.create(
            user=user, type="medication", title="Dori 1", time="08:00"
        )
        other = self.create_patient()
        Treatment.objects.create(
            user=other, type="medication", title="Boshqaning dorisi", time="09:00"
        )

        resp = self.client.get("/api/v1/treatments/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_delete_treatment(self):
        """DELETE /treatments/{id}/ — o'chirish"""
        user = self.auth_as_patient()
        t = Treatment.objects.create(
            user=user, type="medication", title="Delete me", time="08:00"
        )
        resp = self.client.delete(f"/api/v1/treatments/{t.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_unauthenticated(self):
        """GET /treatments/ — login qilmagan"""
        resp = self.client.get("/api/v1/treatments/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class TreatmentMarkTests(BaseAPITestCase):
    """Treatment — mark (bajarildi/o'tkazildi)"""

    def setUp(self):
        super().setUp()
        self.user = self.auth_as_patient()
        self.treatment = Treatment.objects.create(
            user=self.user,
            type="medication",
            title="Aspirin",
            time="08:00",
        )

    def test_mark_completed(self):
        """POST /treatments/{id}/mark/ — bajarildi"""
        resp = self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "completed"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "completed")
        self.assertIsNotNone(resp.data["completed_at"])

    def test_mark_skipped(self):
        """POST /treatments/{id}/mark/ — o'tkazib yuborildi"""
        resp = self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "skipped"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "skipped")

    def test_mark_invalid_status(self):
        """POST /treatments/{id}/mark/ — noto'g'ri status"""
        resp = self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "invalid"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mark_updates_existing_log(self):
        """POST /treatments/{id}/mark/ — qayta belgilaganda yangilanadi"""
        self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/", {"status": "completed"}
        )
        self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/", {"status": "skipped"}
        )
        today = timezone.now().date()
        log = TreatmentLog.objects.get(treatment=self.treatment, date=today)
        self.assertEqual(log.status, "skipped")


class TreatmentStatsTests(BaseAPITestCase):
    """Treatment — statistika va streak"""

    def test_stats_empty(self):
        """GET /treatments/stats/ — bo'sh statistika"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/treatments/stats/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["streak"], 0)

    def test_stats_with_data(self):
        """GET /treatments/stats/ — ma'lumotli statistika"""
        user = self.auth_as_patient()
        t = Treatment.objects.create(
            user=user, type="medication", title="Test", time="08:00"
        )
        today = timezone.now().date()
        TreatmentLog.objects.create(treatment=t, date=today, status="completed")

        resp = self.client.get("/api/v1/treatments/stats/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["completed"], 1)
        self.assertEqual(resp.data["streak"], 1)

    def test_today_me(self):
        """GET /treatments/logs/today-me/ — bugungi muolajalar"""
        user = self.auth_as_patient()
        Treatment.objects.create(
            user=user, type="medication", title="Test", time="08:00"
        )
        resp = self.client.get("/api/v1/treatments/logs/today-me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertFalse(resp.data[0]["is_done"])


class DoctorTreatmentTests(BaseAPITestCase):
    """Treatment — Doctor bemorga muolaja yozish"""

    def test_doctor_prescribe_treatment(self):
        """POST /treatments/doctor/ — bemorga muolaja yozish"""
        doctor = self.auth_as_doctor()
        patient = self.create_patient()
        resp = self.client.post(
            "/api/v1/treatments/doctor/",
            {
                "patient_id": patient.id,
                "type": "medication",
                "title": "Insulin",
                "dosage": "10 birlik",
                "time": "07:00",
                "repeat": "daily",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["created_by_name"], doctor.full_name)

    def test_doctor_prescribe_nonexistent_patient(self):
        """POST /treatments/doctor/ — mavjud bo'lmagan patient"""
        self.auth_as_doctor()
        resp = self.client.post(
            "/api/v1/treatments/doctor/",
            {
                "patient_id": 99999,
                "type": "medication",
                "title": "Test",
                "time": "08:00",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patient_cannot_prescribe(self):
        """POST /treatments/doctor/ — patient yoza olmaydi"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/treatments/doctor/",
            {
                "patient_id": 1,
                "type": "medication",
                "title": "Test",
                "time": "08:00",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TreatmentDeletePreservesHistoryTests(BaseAPITestCase):
    """Muolaja o'chirish — COMPLETED loglar tarixda qoladi, SKIPPED o'chadi"""

    def test_delete_preserves_completed_logs(self):
        """DELETE muolaja — completed loglar saqlanadi"""
        user = self.auth_as_patient()
        t = Treatment.objects.create(
            user=user, type="medication", title="Aspirin", time="08:00"
        )
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        completed_log = TreatmentLog.objects.create(
            treatment=t, date=yesterday, status="completed"
        )

        resp = self.client.delete(f"/api/v1/treatments/{t.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        # Treatment o'chgan
        self.assertFalse(Treatment.objects.filter(id=t.id).exists())

        # COMPLETED log saqlangan (orphaned)
        completed_log.refresh_from_db()
        self.assertIsNone(completed_log.treatment_id)
        self.assertEqual(completed_log.treatment_title, "Aspirin")
        self.assertEqual(completed_log.treatment_type, "medication")
        self.assertEqual(completed_log.user_id, user.id)
        self.assertEqual(completed_log.status, "completed")

    def test_delete_removes_skipped_logs(self):
        """DELETE muolaja — skipped loglar o'chadi"""
        user = self.auth_as_patient()
        t = Treatment.objects.create(
            user=user, type="medication", title="Aspirin", time="08:00"
        )
        today = timezone.now().date()
        skipped_log = TreatmentLog.objects.create(
            treatment=t, date=today, status="skipped"
        )

        resp = self.client.delete(f"/api/v1/treatments/{t.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(TreatmentLog.objects.filter(id=skipped_log.id).exists())

    def test_delete_mixed_logs(self):
        """DELETE muolaja — completed qoladi, skipped o'chadi (aralash)"""
        user = self.auth_as_patient()
        t = Treatment.objects.create(
            user=user, type="medication", title="Mix", time="08:00"
        )
        today = timezone.now().date()
        completed = TreatmentLog.objects.create(
            treatment=t, date=today - timedelta(days=2), status="completed"
        )
        skipped = TreatmentLog.objects.create(
            treatment=t, date=today - timedelta(days=1), status="skipped"
        )

        self.client.delete(f"/api/v1/treatments/{t.id}/")

        self.assertTrue(TreatmentLog.objects.filter(id=completed.id).exists())
        self.assertFalse(TreatmentLog.objects.filter(id=skipped.id).exists())

    def test_orphaned_log_appears_in_stats(self):
        """DELETE'dan keyin orphaned completed log statistikada ko'rinadi"""
        user = self.auth_as_patient()
        t = Treatment.objects.create(
            user=user, type="medication", title="Stats test", time="08:00"
        )
        today = timezone.now().date()
        TreatmentLog.objects.create(treatment=t, date=today, status="completed")

        self.client.delete(f"/api/v1/treatments/{t.id}/")

        resp = self.client.get("/api/v1/treatments/stats/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["completed"], 1)


class TreatmentMarkByDateTests(BaseAPITestCase):
    """mark endpoint — sana bo'yicha (bir kunni o'tkazib yuborish)"""

    def setUp(self):
        super().setUp()
        self.user = self.auth_as_patient()
        self.treatment = Treatment.objects.create(
            user=self.user, type="medication", title="Daily med", time="08:00"
        )

    def test_mark_tomorrow_as_skipped(self):
        """POST mark — ertaga skipped (bir kunni o'chirish)"""
        tomorrow = timezone.now().date() + timedelta(days=1)
        resp = self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "skipped", "date": tomorrow.isoformat()},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["date"], tomorrow.isoformat())
        self.assertEqual(resp.data["status"], "skipped")

        log = TreatmentLog.objects.get(treatment=self.treatment, date=tomorrow)
        self.assertEqual(log.status, "skipped")

    def test_mark_past_date_forbidden(self):
        """POST mark — o'tmish sanaga ruxsat yo'q"""
        yesterday = timezone.now().date() - timedelta(days=1)
        resp = self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "skipped", "date": yesterday.isoformat()},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(
            TreatmentLog.objects.filter(
                treatment=self.treatment, date=yesterday
            ).exists()
        )

    def test_mark_without_date_uses_today(self):
        """POST mark — date berilmasa bugun (eski xulq saqlanadi)"""
        resp = self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "completed"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        today = timezone.now().date()
        self.assertEqual(resp.data["date"], today.isoformat())

    def test_mark_today_then_skip_tomorrow(self):
        """Bugun ichdim + ertaga skip — ikkisi alohida log bo'lib turadi"""
        today = timezone.now().date()
        tomorrow = today + timedelta(days=1)

        # Bugun: ichdim
        self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "completed"},
        )
        # Ertaga: ichmayman
        self.client.post(
            f"/api/v1/treatments/{self.treatment.id}/mark/",
            {"status": "skipped", "date": tomorrow.isoformat()},
        )

        today_log = TreatmentLog.objects.get(
            treatment=self.treatment, date=today
        )
        tomorrow_log = TreatmentLog.objects.get(
            treatment=self.treatment, date=tomorrow
        )
        self.assertEqual(today_log.status, "completed")
        self.assertEqual(tomorrow_log.status, "skipped")
