from unittest.mock import patch

from rest_framework import status

from app.doctors.models import DoctorPatient, DoctorProfile, Specialty
from app.medical.models import MedicalNote, MedicalNoteImage
from tests.base import BaseAPITestCase


class MedicalNoteImageTests(BaseAPITestCase):
    """MedicalNote rasm biriktirish + upload URL flowi"""

    def setUp(self):
        super().setUp()
        self.specialty = Specialty.objects.create(name="Terapevt", icon="stethoscope")

    def _link_doctor_patient(self, doctor_user, patient_user):
        profile, _ = DoctorProfile.objects.get_or_create(
            user=doctor_user, defaults={"specialty": self.specialty}
        )
        DoctorPatient.objects.create(
            doctor=profile,
            patient=patient_user,
            added_by=DoctorPatient.AddedBy.DOCTOR,
            status=DoctorPatient.Status.ACCEPTED,
        )
        return profile

    # --- Upload URL endpoint ---

    @patch("app.medical.views.generate_upload_url", return_value="https://example.com/upload")
    def test_image_upload_url_single(self, mock_gen):
        self.auth_as_doctor()
        resp = self.client.post(
            "/api/v1/medical/notes/image-upload-url/",
            {"file_type": "image/jpeg", "count": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertIn("items", data)
        self.assertEqual(len(data["items"]), 1)
        item = data["items"][0]
        self.assertEqual(item["upload_url"], "https://example.com/upload")
        self.assertTrue(item["file_key"].startswith("medical-notes/"))
        self.assertTrue(item["file_key"].endswith(".jpg"))
        self.assertEqual(item["expires_in"], 900)
        mock_gen.assert_called_once()

    @patch("app.medical.views.generate_upload_url", return_value="https://example.com/upload")
    def test_image_upload_url_multiple(self, mock_gen):
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/medical/notes/image-upload-url/",
            {"file_type": "image/png", "count": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        items = resp.json()["items"]
        self.assertEqual(len(items), 3)
        keys = {it["file_key"] for it in items}
        self.assertEqual(len(keys), 3, "file_key'lar unique bo'lishi kerak")
        for it in items:
            self.assertTrue(it["file_key"].endswith(".png"))
        self.assertEqual(mock_gen.call_count, 3)

    def test_image_upload_url_requires_auth(self):
        resp = self.client.post(
            "/api/v1/medical/notes/image-upload-url/",
            {"file_type": "image/jpeg", "count": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_image_upload_url_count_exceeds_max(self):
        self.auth_as_doctor()
        resp = self.client.post(
            "/api/v1/medical/notes/image-upload-url/",
            {"file_type": "image/jpeg", "count": 6},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_image_upload_url_invalid_mime(self):
        self.auth_as_doctor()
        resp = self.client.post(
            "/api/v1/medical/notes/image-upload-url/",
            {"file_type": "application/exe", "count": 1},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # --- Note create with images ---

    def test_patient_creates_note_with_images(self):
        patient = self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/medical/notes/",
            {
                "text": "O'zim haqimda eslatma",
                "images_input": [
                    {
                        "file_key": "medical-notes/1/abc.jpg",
                        "file_mime": "image/jpeg",
                        "original_name": "front.jpg",
                    },
                    {
                        "file_key": "medical-notes/1/xyz.jpg",
                        "file_mime": "image/jpeg",
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        body = resp.json()
        self.assertEqual(len(body["images"]), 2)
        self.assertEqual(body["images"][0]["order"], 0)
        self.assertEqual(body["images"][1]["order"], 1)
        self.assertEqual(body["images"][0]["original_name"], "front.jpg")
        # DB confirmation
        note = MedicalNote.objects.get(id=body["id"])
        self.assertEqual(note.user, patient)
        self.assertEqual(note.images.count(), 2)

    def test_doctor_creates_note_for_linked_patient_with_images(self):
        patient = self.create_patient()
        doctor = self.auth_as_doctor()
        self._link_doctor_patient(doctor, patient)

        resp = self.client.post(
            "/api/v1/medical/notes/",
            {
                "patient_id": patient.id,
                "text": "Klinik kuzatuv",
                "images_input": [
                    {"file_key": "medical-notes/2/scan.jpg", "file_mime": "image/jpeg"},
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        body = resp.json()
        self.assertEqual(body["user"], patient.id)
        self.assertEqual(body["created_by"], doctor.id)
        self.assertEqual(len(body["images"]), 1)
        self.assertEqual(body["images"][0]["file_key"], "medical-notes/2/scan.jpg")

    def test_create_note_image_only_no_text(self):
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/medical/notes/",
            {
                "text": "",
                "images_input": [
                    {"file_key": "medical-notes/1/only.jpg", "file_mime": "image/jpeg"},
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertEqual(len(resp.json()["images"]), 1)

    def test_create_note_rejects_empty(self):
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/medical/notes/",
            {"text": "", "images_input": []},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # --- List/retrieve images ---

    def test_list_note_includes_images_with_signed_url(self):
        patient = self.auth_as_patient()
        note = MedicalNote.objects.create(user=patient, text="X")
        MedicalNoteImage.objects.create(
            note=note, file_key="medical-notes/1/a.jpg", order=0
        )
        MedicalNoteImage.objects.create(
            note=note, file_key="medical-notes/1/b.jpg", order=1
        )

        resp = self.client.get("/api/v1/medical/notes/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.json().get("results", resp.json())
        # bizning yozuv ichida images ro'yxati
        my = next(r for r in results if r["id"] == note.id)
        self.assertEqual(len(my["images"]), 2)
        # ordering: order asc
        self.assertEqual(my["images"][0]["file_key"], "medical-notes/1/a.jpg")
        self.assertIsNotNone(my["images"][0]["file_url"])

    # --- Patch (append) ---

    def test_patch_note_appends_images(self):
        patient = self.auth_as_patient()
        note = MedicalNote.objects.create(user=patient, text="orig", created_by=patient)
        MedicalNoteImage.objects.create(
            note=note, file_key="medical-notes/1/a.jpg", order=0
        )

        resp = self.client.patch(
            f"/api/v1/medical/notes/{note.id}/",
            {
                "images_input": [
                    {"file_key": "medical-notes/1/b.jpg", "file_mime": "image/jpeg"},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        note.refresh_from_db()
        self.assertEqual(note.images.count(), 2)
        ordered = list(note.images.order_by("order").values_list("file_key", "order"))
        self.assertEqual(ordered, [("medical-notes/1/a.jpg", 0), ("medical-notes/1/b.jpg", 1)])

    # --- Delete image ---

    def test_author_can_delete_image(self):
        patient = self.auth_as_patient()
        note = MedicalNote.objects.create(user=patient, text="x", created_by=patient)
        img = MedicalNoteImage.objects.create(
            note=note, file_key="medical-notes/1/a.jpg", order=0
        )

        resp = self.client.delete(
            f"/api/v1/medical/notes/{note.id}/images/{img.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MedicalNoteImage.objects.filter(id=img.id).exists())

    def test_non_author_cannot_delete_image(self):
        # doctor yozgan note — patient o'chira olmasligi kerak
        patient = self.create_patient()
        doctor = self.create_doctor()
        self._link_doctor_patient(doctor, patient)
        note = MedicalNote.objects.create(user=patient, text="x", created_by=doctor)
        img = MedicalNoteImage.objects.create(
            note=note, file_key="medical-notes/1/a.jpg", order=0
        )

        # patient sifatida login
        self.authenticate(patient)
        resp = self.client.delete(
            f"/api/v1/medical/notes/{note.id}/images/{img.id}/"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(MedicalNoteImage.objects.filter(id=img.id).exists())

    def test_delete_missing_image_returns_404(self):
        patient = self.auth_as_patient()
        note = MedicalNote.objects.create(user=patient, text="x", created_by=patient)
        resp = self.client.delete(
            f"/api/v1/medical/notes/{note.id}/images/99999/"
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cascade_delete_note_removes_images(self):
        patient = self.auth_as_patient()
        note = MedicalNote.objects.create(user=patient, text="x", created_by=patient)
        MedicalNoteImage.objects.create(
            note=note, file_key="medical-notes/1/a.jpg", order=0
        )
        note_id = note.id
        note.delete()
        self.assertEqual(
            MedicalNoteImage.objects.filter(note_id=note_id).count(), 0
        )
