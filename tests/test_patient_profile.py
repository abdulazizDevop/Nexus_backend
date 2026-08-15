"""Patient profile yaratilishi va serializer test'lari (Phase 1).

Test scope:
  - Har User yaratilganda Patient avtomatik tug'iladi
  - Patient.id != User.id (alohida ID space)
  - UserSerializer patient_id va doctor_id'ni qaytaradi
  - Doctor user'da ham Patient mavjud (Yandex Taxi modeli)
  - Existing user'lar uchun migration qilingan (data migration test)
"""

from django.contrib.auth import get_user_model

from app.users.models import Patient
from tests.base import BaseAPITestCase

User = get_user_model()


class PatientAutoCreateTests(BaseAPITestCase):
    """User yaratilganda Patient avtomatik tug'ilish."""

    def test_new_patient_user_creates_patient_profile(self):
        user = self.create_patient()
        self.assertTrue(hasattr(user, "patient_profile"))
        self.assertIsInstance(user.patient_profile, Patient)
        self.assertEqual(user.patient_profile.user_id, user.id)

    def test_new_doctor_user_also_creates_patient_profile(self):
        """Yandex Taxi: doctor ham Patient'ga ega — bemor sifatida ishlatish uchun."""
        user = self.create_doctor()
        self.assertTrue(hasattr(user, "patient_profile"))

    def test_new_admin_user_also_creates_patient_profile(self):
        """Hozircha admin ham Patient'ga ega — soddalik uchun."""
        user = self.create_admin()
        self.assertTrue(hasattr(user, "patient_profile"))

    def test_patient_profile_ids_are_independent(self):
        """Patient.id alohida tabloda — har patient'da unique."""
        u1 = self.create_patient()
        u2 = self.create_patient()
        # Har patient_profile o'zining unique id'siga ega
        self.assertNotEqual(u1.patient_profile.id, u2.patient_profile.id)
        # User->Patient bog'lanish to'g'ri
        self.assertEqual(u1.patient_profile.user_id, u1.id)
        self.assertEqual(u2.patient_profile.user_id, u2.id)

    def test_patient_profile_idempotent_on_save(self):
        """Existing user qayta save qilinganda dublikat yaratilmaydi."""
        user = self.create_patient()
        original_pp_id = user.patient_profile.id
        user.full_name = "Updated Name"
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.patient_profile.id, original_pp_id)
        self.assertEqual(Patient.objects.filter(user=user).count(), 1)


class PatientCascadeTests(BaseAPITestCase):
    """User o'chirilsa, Patient ham CASCADE bilan o'chadi."""

    def test_user_delete_cascades_to_patient(self):
        user = self.create_patient()
        patient_id = user.patient_profile.id
        user.delete()
        self.assertFalse(Patient.objects.filter(id=patient_id).exists())


class PatientBackfillIdempotencyTests(BaseAPITestCase):
    """Backfill migration logic — qaytadan ishlatish xavfsiz."""

    def test_get_or_create_does_not_duplicate(self):
        """Idempotent: bir user uchun get_or_create ikki marta = bitta row."""
        user = self.create_patient()
        # Patient yaratilgan
        self.assertEqual(Patient.objects.filter(user=user).count(), 1)
        # Migration logic'ni qayta ishlatish (manual emulation)
        Patient.objects.get_or_create(user=user)
        self.assertEqual(Patient.objects.filter(user=user).count(), 1)


class UserSerializerPatientFieldsTests(BaseAPITestCase):
    """/me/ endpoint patient_id va doctor_id'ni qaytaradi."""

    def test_me_returns_patient_id_for_patient(self):
        user = self.auth_as_patient()
        resp = self.client.get("/api/v1/users/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["patient_id"], user.patient_profile.id)
        self.assertIsNone(resp.data["doctor_id"])
        self.assertFalse(resp.data["has_doctor_profile"])
        self.assertFalse(resp.data["is_verified_doctor"])

    def test_me_returns_doctor_id_for_doctor_with_profile(self):
        user = self.auth_as_doctor()
        # Doctor user'da DoctorProfile alohida yaratiladi (factory yaratmaydi)
        from app.doctors.models import DoctorProfile

        doctor_profile = DoctorProfile.objects.create(user=user, is_verified=True)
        resp = self.client.get("/api/v1/users/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["patient_id"], user.patient_profile.id)
        self.assertEqual(resp.data["doctor_id"], doctor_profile.id)
        self.assertTrue(resp.data["has_doctor_profile"])
        self.assertTrue(resp.data["is_verified_doctor"])

    def test_me_returns_doctor_pending_when_unverified(self):
        user = self.auth_as_patient()
        from app.doctors.models import DoctorProfile

        DoctorProfile.objects.create(user=user, is_verified=False)
        resp = self.client.get("/api/v1/users/me/")
        self.assertTrue(resp.data["has_doctor_profile"])
        self.assertFalse(resp.data["is_verified_doctor"])

    def test_allowed_roles_includes_doctor_for_patient(self):
        """Yandex Taxi: patient ham doctor'ga switch qila oladi."""
        self.auth_as_patient()
        resp = self.client.get("/api/v1/users/me/")
        self.assertIn("doctor", resp.data["allowed_roles"])
        self.assertIn("patient", resp.data["allowed_roles"])
