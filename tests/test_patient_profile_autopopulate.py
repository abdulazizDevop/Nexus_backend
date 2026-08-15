"""Phase 3 Slice 2: model.save() patient_profile'ni auto-populate qiladi.

Backwards compatible — eski kod patient/user yuborganda yangi patient_profile FK
avtomatik to'ldiriladi. Yangi kod ham yuborishi mumkin (idempotent).
"""

from datetime import date, time

from app.doctors.models import DoctorProfile
from tests.base import BaseAPITestCase


class AppointmentAutoPopulateTests(BaseAPITestCase):
    def test_appointment_save_populates_patient_profile(self):
        from app.meetings.models import Appointment

        patient_user = self.create_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        appt = Appointment.objects.create(
            patient=patient_user,
            doctor=doctor_profile,
            date=date(2026, 6, 1),
            start_time=time(10, 0),
            end_time=time(11, 0),
            meeting_type="online",
            status="pending",
        )
        appt.refresh_from_db()
        self.assertEqual(appt.patient_profile_id, patient_user.patient_profile.id)


class TreatmentAutoPopulateTests(BaseAPITestCase):
    def test_treatment_save_populates_patient_profile(self):
        from app.treatment.models import Treatment

        user = self.create_patient()
        t = Treatment.objects.create(
            user=user,
            type="medication",
            title="Aspirin",
            time=time(8, 0),
        )
        t.refresh_from_db()
        self.assertEqual(t.patient_profile_id, user.patient_profile.id)


class HealthIndicatorAutoPopulateTests(BaseAPITestCase):
    def test_health_indicator_save_populates_patient_profile(self):
        from app.health_packages.models import HealthIndicator, HealthIndicatorType

        user = self.create_patient()
        ind_type = HealthIndicatorType.objects.create(name="Vazn", unit="kg")
        ind = HealthIndicator.objects.create(
            user=user,
            indicator_type=ind_type,
            value=70.5,
            date=date(2026, 6, 1),
        )
        ind.refresh_from_db()
        self.assertEqual(ind.patient_profile_id, user.patient_profile.id)


class DailyCheckupAutoPopulateTests(BaseAPITestCase):
    def test_daily_checkup_save_populates_patient_profile(self):
        from app.health_packages.models import DailySituationCheckup

        user = self.create_patient()
        c = DailySituationCheckup.objects.create(
            user=user,
            date=date(2026, 6, 1),
            status="good",
        )
        c.refresh_from_db()
        self.assertEqual(c.patient_profile_id, user.patient_profile.id)
