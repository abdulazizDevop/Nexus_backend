from datetime import date, time, timedelta

from rest_framework import status

from app.doctors.models import DoctorProfile, Slot, Specialty
from app.meetings.models import Appointment
from tests.base import BaseAPITestCase


class PatientAppointmentTests(BaseAPITestCase):
    """Meetings — Patient endpointlar"""

    def setUp(self):
        super().setUp()
        self.doctor_user = self.create_doctor()
        specialty = Specialty.objects.create(name="Kardiolog")
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            specialty=specialty,
            is_verified=True,
        )
        # Keyingi dushanba (isoweekday: 1=Monday)
        today = date.today()
        days_ahead = 1 - today.isoweekday()
        if days_ahead <= 0:
            days_ahead += 7
        self.next_monday = today + timedelta(days=days_ahead)
        # 09:00–17:00 oralig'ida 30 daqiqalik bo'sh slotlar (eski recurring
        # DoctorSchedule o'rniga — model o'chirilgan, endi alohida Slot qatorlari).
        for minutes in range(9 * 60, 17 * 60, 30):
            start_t = time(minutes // 60, minutes % 60)
            end_t = time((minutes + 30) // 60, (minutes + 30) % 60)
            Slot.objects.create(
                doctor=self.profile,
                date=self.next_monday,
                start_time=start_t,
                end_time=end_t,
                status=Slot.Status.FREE,
            )

    def test_book_appointment_success(self):
        """POST /meetings/patient/ — uchrashuvga yozilish"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/meetings/patient/",
            {
                "doctor_id": self.profile.id,
                "date": str(self.next_monday),
                "start_time": "09:00",
                "end_time": "09:30",
                "meeting_type": "offline",
                "reason": "Konsultatsiya kerak",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "pending")

    def test_book_appointment_past_date(self):
        """POST /meetings/patient/ — o'tgan sanaga yozilish mumkin emas"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/meetings/patient/",
            {
                "doctor_id": self.profile.id,
                "date": "2020-01-01",
                "start_time": "09:00",
                "end_time": "09:30",
                "meeting_type": "offline",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_book_appointment_unauthenticated(self):
        """POST /meetings/patient/ — login qilmagan"""
        resp = self.client.post("/api/v1/meetings/patient/", {})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_cancel_appointment(self):
        """POST /meetings/patient/{id}/cancel/ — bekor qilish"""
        patient = self.auth_as_patient()
        appt = Appointment.objects.create(
            patient=patient,
            doctor=self.profile,
            date=self.next_monday,
            start_time="09:00",
            end_time="09:30",
            meeting_type="offline",
            status="pending",
        )
        resp = self.client.post(f"/api/v1/meetings/patient/{appt.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "cancelled")

    def test_cancel_completed_appointment_fails(self):
        """POST /meetings/patient/{id}/cancel/ — tugallanganni bekor qilib bo'lmaydi"""
        patient = self.auth_as_patient()
        appt = Appointment.objects.create(
            patient=patient,
            doctor=self.profile,
            date=self.next_monday,
            start_time="09:00",
            end_time="09:30",
            meeting_type="offline",
            status="completed",
        )
        resp = self.client.post(f"/api/v1/meetings/patient/{appt.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class DoctorAppointmentTests(BaseAPITestCase):
    """Meetings — Doctor endpointlar"""

    def setUp(self):
        super().setUp()
        self.doctor_user = self.create_doctor()
        specialty = Specialty.objects.create(name="Terapevt")
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            specialty=specialty,
        )
        self.patient = self.create_patient()
        self.next_date = date.today() + timedelta(days=7)
        self.appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.profile,
            date=self.next_date,
            start_time="10:00",
            end_time="10:30",
            meeting_type="offline",
            status="pending",
        )

    def test_approve_success(self):
        """POST /meetings/doctor/{id}/approve/ — tasdiqlash"""
        self.authenticate(self.doctor_user)
        resp = self.client.post(f"/api/v1/meetings/doctor/{self.appt.id}/approve/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "approved")

    def test_reject_success(self):
        """POST /meetings/doctor/{id}/reject/ — rad etish"""
        self.authenticate(self.doctor_user)
        resp = self.client.post(
            f"/api/v1/meetings/doctor/{self.appt.id}/reject/",
            {"reject_reason": "Vaqtim yo'q"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "rejected")

    def test_reject_without_reason_fails(self):
        """POST /meetings/doctor/{id}/reject/ — sabab yo'q bo'lsa xato"""
        self.authenticate(self.doctor_user)
        resp = self.client.post(f"/api/v1/meetings/doctor/{self.appt.id}/reject/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_approved_appointment(self):
        """POST /meetings/doctor/{id}/complete/ — yakunlash"""
        self.appt.status = "approved"
        self.appt.save()
        self.authenticate(self.doctor_user)
        resp = self.client.post(f"/api/v1/meetings/doctor/{self.appt.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_complete_pending_fails(self):
        """POST /meetings/doctor/{id}/complete/ — pending ni yakunlash mumkin emas"""
        self.authenticate(self.doctor_user)
        resp = self.client.post(f"/api/v1/meetings/doctor/{self.appt.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patient_cannot_approve(self):
        """POST /meetings/doctor/{id}/approve/ — patient uchun 403"""
        self.authenticate(self.patient)
        resp = self.client.post(f"/api/v1/meetings/doctor/{self.appt.id}/approve/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
