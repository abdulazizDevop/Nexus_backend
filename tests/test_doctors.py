from rest_framework import status

from app.doctors.models import DoctorProfile, Slot, Specialty
from tests.base import BaseAPITestCase


class DoctorProfileTests(BaseAPITestCase):
    """Doctor — Profil endpointlar"""

    def setUp(self):
        super().setUp()
        self.specialty = Specialty.objects.create(name="Kardiolog", icon="heart")

    def test_list_doctors(self):
        """GET /doctors/profiles/ — doktorlar ro'yxati"""
        doctor = self.create_doctor()
        DoctorProfile.objects.create(user=doctor, specialty=self.specialty)
        self.auth_as_patient()
        resp = self.client.get("/api/v1/doctors/profiles/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_list_doctors_unauthenticated(self):
        """GET /doctors/profiles/ — login qilmagan"""
        resp = self.client.get("/api/v1/doctors/profiles/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_doctor_me_success(self):
        """GET /doctors/profiles/me/ — doctor o'z profilini ko'radi"""
        doctor = self.auth_as_doctor()
        DoctorProfile.objects.create(user=doctor, specialty=self.specialty)
        resp = self.client.get("/api/v1/doctors/profiles/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_doctor_me_patient_forbidden(self):
        """GET /doctors/profiles/me/ — patient kirsa 403"""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/doctors/profiles/me/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_doctor_me_update(self):
        """PATCH /doctors/profiles/me/ — profilni yangilash"""
        doctor = self.auth_as_doctor()
        DoctorProfile.objects.create(user=doctor, specialty=self.specialty)
        resp = self.client.patch(
            "/api/v1/doctors/profiles/me/",
            {"bio": "Tajribali kardiolog", "experience_years": 10},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_verify_doctor_super_admin(self):
        """PATCH /doctors/profiles/{id}/verify/ — super admin tasdiqlaydi"""
        self.auth_as_admin(admin_type="super")
        doctor = self.create_doctor()
        profile = DoctorProfile.objects.create(user=doctor, specialty=self.specialty)
        resp = self.client.patch(
            f"/api/v1/doctors/profiles/{profile.id}/verify/",
            {"is_verified": True},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        profile.refresh_from_db()
        self.assertTrue(profile.is_verified)

    def test_verify_doctor_patient_forbidden(self):
        """PATCH /doctors/profiles/{id}/verify/ — patient uchun 403"""
        self.auth_as_patient()
        doctor = self.create_doctor()
        profile = DoctorProfile.objects.create(user=doctor, specialty=self.specialty)
        resp = self.client.patch(f"/api/v1/doctors/profiles/{profile.id}/verify/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_doctor_patients_list(self):
        """GET /doctors/profiles/me/patients/ — bemorlar ro'yxati"""
        doctor = self.auth_as_doctor()
        DoctorProfile.objects.create(user=doctor, specialty=self.specialty)
        patient = self.create_patient()
        patient.referred_by = doctor
        patient.save(update_fields=["referred_by"])
        resp = self.client.get("/api/v1/doctors/profiles/me/patients/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)


class ScheduleTests(BaseAPITestCase):
    """Doctor — Slot (jadval) endpointlar"""

    def setUp(self):
        super().setUp()
        self.doctor = self.auth_as_doctor()
        self.specialty = Specialty.objects.create(name="Terapevt")
        DoctorProfile.objects.create(user=self.doctor, specialty=self.specialty)
        from datetime import date, timedelta

        today = date.today()
        days_ahead = 1 - today.isoweekday()  # 1 = dushanba
        if days_ahead <= 0:
            days_ahead += 7
        self.next_monday = today + timedelta(days=days_ahead)

    def test_create_schedule(self):
        """POST /doctors/me/slots/sync/ — slot yaratish"""
        resp = self.client.post(
            "/api/v1/doctors/me/slots/sync/",
            {
                "create": [
                    {
                        "date": str(self.next_monday),
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "status": "free",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["created"]), 1)
        self.assertEqual(
            Slot.objects.filter(doctor__user=self.doctor).count(), 1
        )

    def test_create_schedule_duplicate_weekday_updates(self):
        """POST /doctors/me/slots/sync/ — bitta requestda ikki slot yaratish"""
        resp = self.client.post(
            "/api/v1/doctors/me/slots/sync/",
            {
                "create": [
                    {
                        "date": str(self.next_monday),
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "status": "free",
                    },
                    {
                        "date": str(self.next_monday),
                        "start_time": "10:00",
                        "end_time": "10:30",
                        "status": "free",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            Slot.objects.filter(doctor__user=self.doctor).count(), 2
        )

    def test_create_schedule_patient_forbidden(self):
        """POST /doctors/me/slots/sync/ — patient uchun 403"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/doctors/me/slots/sync/",
            {
                "create": [
                    {
                        "date": str(self.next_monday),
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "status": "free",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_slots_generation(self):
        """GET /doctors/profiles/{id}/slots/?date= — bo'sh slotlar ro'yxati"""
        import datetime

        profile = DoctorProfile.objects.get(user=self.doctor)
        Slot.objects.create(
            doctor=profile,
            date=self.next_monday,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(9, 30),
            status=Slot.Status.FREE,
        )
        Slot.objects.create(
            doctor=profile,
            date=self.next_monday,
            start_time=datetime.time(10, 0),
            end_time=datetime.time(10, 30),
            status=Slot.Status.FREE,
        )
        self.auth_as_patient()
        resp = self.client.get(
            f"/api/v1/doctors/{profile.id}/slots/?date={self.next_monday}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class SpecialtyTests(BaseAPITestCase):
    """Doctor — Mutaxassisliklar"""

    def test_list_specialties(self):
        """GET /doctors/specialties/ — ro'yxat"""
        created = Specialty.objects.create(name="Kardiolog")
        self.auth_as_patient()
        resp = self.client.get("/api/v1/doctors/specialties/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # List paginatsiyalangan (DEFAULT_PAGINATION_CLASS) — {count, ..., results}.
        # Seed/setUp specialty'lardan mustaqil: faqat o'zimiz yaratganni tekshiramiz.
        rows = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertIn(created.id, [r["id"] for r in rows])

    def test_create_specialty_admin(self):
        """POST /doctors/specialties/ — admin yaratadi"""
        self.auth_as_admin()
        resp = self.client.post(
            "/api/v1/doctors/specialties/",
            {
                "name": {"uz": "Nevropatolog", "ru": "Невропатолог", "cyr": "Невропатолог"},
                "icon": "brain",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

    def test_create_specialty_patient_forbidden(self):
        """POST /doctors/specialties/ — patient yarata olmaydi"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/doctors/specialties/",
            {
                "name": "Nevropatolog",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
