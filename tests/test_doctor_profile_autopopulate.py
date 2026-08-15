"""Phase 3 Slice 5: doctor_profile auto-populate (creator/updater Doctor FK).

Test scope:
  - Treatment.doctor_profile from created_by (if doctor)
  - DailyCalorieLimit.doctor_profile from set_by
  - MedicalCard/Condition/Note doctor_profile from updated_by/added_by/created_by
  - DietRestriction.doctor_profile from doctor (User FK)
  - If user is NOT a doctor (admin / patient), doctor_profile stays null
"""

from datetime import date, time

from app.doctors.models import DoctorProfile
from tests.base import BaseAPITestCase


class TreatmentDoctorProfileTests(BaseAPITestCase):
    def test_doctor_profile_set_when_creator_is_doctor(self):
        from app.treatment.models import Treatment

        patient = self.create_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        t = Treatment.objects.create(
            user=patient,
            created_by=doctor_user,
            type="medication",
            title="Test",
            time=time(8, 0),
        )
        t.refresh_from_db()
        self.assertEqual(t.doctor_profile_id, doctor_profile.id)

    def test_doctor_profile_null_when_patient_self_added(self):
        from app.treatment.models import Treatment

        patient = self.create_patient()
        t = Treatment.objects.create(
            user=patient,
            created_by=patient,  # patient self-add
            type="medication",
            title="Self add",
            time=time(8, 0),
        )
        t.refresh_from_db()
        self.assertIsNone(t.doctor_profile_id)


class DietRestrictionDoctorProfileTests(BaseAPITestCase):
    def test_doctor_profile_set_when_doctor_user_provided(self):
        from app.diet_ai.models import DietRestriction

        patient = self.create_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        r = DietRestriction.objects.create(
            patient=patient,
            doctor=doctor_user,
            rule="shakarsiz",
        )
        r.refresh_from_db()
        self.assertEqual(r.doctor_profile_id, doctor_profile.id)


class MedicalDoctorProfileTests(BaseAPITestCase):
    def test_medical_note_doctor_profile(self):
        from app.medical.models import MedicalNote

        patient = self.create_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        n = MedicalNote.objects.create(
            user=patient,
            text="Test note",
            created_by=doctor_user,
        )
        n.refresh_from_db()
        self.assertEqual(n.doctor_profile_id, doctor_profile.id)
        # Patient profile ham populate qilingan
        self.assertEqual(n.patient_profile_id, patient.patient_profile.id)
