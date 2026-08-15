from rest_framework import status

from app.doctors.models import DoctorPatient, DoctorProfile, Specialty
from app.medical.models import MedicalCondition, MedicalNote
from tests.base import BaseAPITestCase


class MedicalNoteDetailAccessTests(BaseAPITestCase):
    """Bug fix: doctor eski yozuvni `?patient_id=` bermasdan ham
    ocha/tahrirlay/o'chira olishi kerak."""

    def setUp(self):
        super().setUp()
        self.specialty = Specialty.objects.create(name="Kardiolog")
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
        self.note = MedicalNote.objects.create(
            user=self.patient,
            text="Bosim 120/80, holat barqaror",
            created_by=self.doctor_user,
        )

    def test_doctor_retrieve_note_without_patient_id(self):
        """GET /notes/{id}/ — doctor `?patient_id=` bermasdan eski yozuvni ko'ra oladi."""
        self.authenticate(self.doctor_user)
        resp = self.client.get(f"/api/v1/medical/notes/{self.note.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["id"], self.note.id)
        self.assertEqual(resp.data["text"], "Bosim 120/80, holat barqaror")

    def test_doctor_retrieve_note_with_patient_id_still_works(self):
        """GET /notes/{id}/?patient_id=5 — eski usul ham ishlaydi (regression check)."""
        self.authenticate(self.doctor_user)
        resp = self.client.get(
            f"/api/v1/medical/notes/{self.note.id}/?patient_id={self.patient.id}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_doctor_patch_note_without_patient_id(self):
        """PATCH /notes/{id}/ — muallif doctor tahrirlay oladi."""
        self.authenticate(self.doctor_user)
        resp = self.client.patch(
            f"/api/v1/medical/notes/{self.note.id}/",
            {"text": "Yangilangan matn"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.note.refresh_from_db()
        self.assertEqual(self.note.text, "Yangilangan matn")

    def test_doctor_delete_note_without_patient_id(self):
        """DELETE /notes/{id}/ — muallif doctor o'chira oladi."""
        self.authenticate(self.doctor_user)
        resp = self.client.delete(f"/api/v1/medical/notes/{self.note.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MedicalNote.objects.filter(id=self.note.id).exists())

    def test_other_doctor_cannot_retrieve(self):
        """Boshqa doctor (bog'lanmagan) yozuvni ko'rolmaydi → 404."""
        other_doctor = self.create_doctor(phone="998900000999")
        DoctorProfile.objects.create(user=other_doctor, specialty=self.specialty)
        self.authenticate(other_doctor)
        resp = self.client.get(f"/api/v1/medical/notes/{self.note.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_doctor_cannot_patch(self):
        """Boshqa doctor tahrirlay olmasligi kerak → 404."""
        other_doctor = self.create_doctor(phone="998900000998")
        DoctorProfile.objects.create(user=other_doctor, specialty=self.specialty)
        self.authenticate(other_doctor)
        resp = self.client.patch(
            f"/api/v1/medical/notes/{self.note.id}/",
            {"text": "hack"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_doctor_only_pending_relationship_blocked(self):
        """Faqat pending status — accepted emas → 404."""
        new_patient = self.create_patient(phone="998900001111")
        DoctorPatient.objects.create(
            doctor=self.profile,
            patient=new_patient,
            status=DoctorPatient.Status.PENDING,
            added_by=DoctorPatient.AddedBy.DOCTOR,
        )
        pending_note = MedicalNote.objects.create(
            user=new_patient,
            text="kutilayotgan bemor yozuvi",
            created_by=self.doctor_user,
        )
        self.authenticate(self.doctor_user)
        resp = self.client.get(f"/api/v1/medical/notes/{pending_note.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_author_doctor_cannot_patch(self):
        """Bemor 2 doctor'ga bog'langan; doctor B muallif emas — PATCH 403."""
        doctor_b = self.create_doctor(phone="998900002222")
        profile_b = DoctorProfile.objects.create(user=doctor_b, specialty=self.specialty)
        DoctorPatient.objects.create(
            doctor=profile_b,
            patient=self.patient,
            status=DoctorPatient.Status.ACCEPTED,
            added_by=DoctorPatient.AddedBy.DOCTOR,
        )
        self.authenticate(doctor_b)
        resp = self.client.patch(
            f"/api/v1/medical/notes/{self.note.id}/",
            {"text": "begona doctor"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_patient_can_retrieve_own_note(self):
        """Bemor o'z yozuvini ko'ra oladi (patient_id'siz)."""
        self.authenticate(self.patient)
        resp = self.client.get(f"/api/v1/medical/notes/{self.note.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_patient_cannot_retrieve_others_note(self):
        """Boshqa bemor yozuvini ko'rolmaydi."""
        other_patient = self.create_patient(phone="998900003333")
        self.authenticate(other_patient)
        resp = self.client.get(f"/api/v1/medical/notes/{self.note.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class MedicalNoteListTests(BaseAPITestCase):
    """List endpoint regression: ?patient_id= ishlashida davom etadi."""

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
        MedicalNote.objects.create(
            user=self.patient, text="n1", created_by=self.doctor_user
        )
        MedicalNote.objects.create(
            user=self.patient, text="n2", created_by=self.doctor_user
        )

    def test_doctor_list_with_patient_id(self):
        self.authenticate(self.doctor_user)
        resp = self.client.get(
            f"/api/v1/medical/notes/?patient_id={self.patient.id}"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertEqual(len(results), 2)

    def test_patient_list_own(self):
        self.authenticate(self.patient)
        resp = self.client.get("/api/v1/medical/notes/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertEqual(len(results), 2)


class MedicalConditionDetailAccessTests(BaseAPITestCase):
    """Conditions endpoint — bir xil bug fix."""

    def setUp(self):
        super().setUp()
        self.specialty = Specialty.objects.create(name="Allergolog")
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
        self.cond = MedicalCondition.objects.create(
            user=self.patient,
            type=MedicalCondition.Type.ALLERGY,
            name="Yong'oq",
            severity=MedicalCondition.Severity.HIGH,
            added_by=self.doctor_user,
        )

    def test_doctor_retrieve_condition_without_patient_id(self):
        self.authenticate(self.doctor_user)
        resp = self.client.get(f"/api/v1/medical/conditions/{self.cond.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["name"], "Yong'oq")

    def test_doctor_patch_condition_without_patient_id(self):
        self.authenticate(self.doctor_user)
        resp = self.client.patch(
            f"/api/v1/medical/conditions/{self.cond.id}/",
            {"severity": MedicalCondition.Severity.LOW},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.cond.refresh_from_db()
        self.assertEqual(self.cond.severity, MedicalCondition.Severity.LOW)

    def test_other_doctor_cannot_retrieve_condition(self):
        other_doctor = self.create_doctor(phone="998900004444")
        DoctorProfile.objects.create(user=other_doctor, specialty=self.specialty)
        self.authenticate(other_doctor)
        resp = self.client.get(f"/api/v1/medical/conditions/{self.cond.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
