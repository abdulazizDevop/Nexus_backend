"""Bugun tuzatilgan ikki bug uchun testlar:

1. submit endpoint AnalysisFile yaratadi va status SUBMITTED ga o'tadi
2. AnalysisType.category — response'da `type_category` qaytaradi va
   `?category=` filter ishlaydi
"""
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from app.doctors.models import DoctorPatient, DoctorProfile, Specialty
from app.medical.models import (
    Analysis,
    AnalysisFile,
    AnalysisType,
)
from tests.base import BaseAPITestCase


def _make_type(code, category, name_uz="Test"):
    return AnalysisType.objects.create(
        code=code,
        name={"uz": name_uz},
        category=category,
        is_active=True,
    )


# Submit endpoint har file_key uchun S3'dan HeadObject bilan real MIME/size'ni
# tekshiradi (services.storage.head_object_or_none). Testlarda S3 yo'q —
# fayl kengaytmasiga qarab to'g'ri (allowed) MIME va yaroqli size qaytaramiz.
# View import'ni funksiya ichida qiladi, shuning uchun manba modulni patch qilamiz.
def _fake_head_object(file_key):
    key = str(file_key).lower()
    if key.endswith(".pdf"):
        content_type = "application/pdf"
    elif key.endswith(".png"):
        content_type = "image/png"
    else:
        content_type = "image/jpeg"
    return {"size": 1024, "content_type": content_type}


class AnalysisSubmitFileTests(BaseAPITestCase):
    """Bug 1: submit AnalysisFile yaratsin, status SUBMITTED ga o'tsin."""

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
        self.atype = _make_type("blood-biochem-test", "blood", "Bioximik")
        self.analysis = Analysis.objects.create(
            patient=self.patient,
            doctor=self.doctor_user,
            type=self.atype,
            deadline_at=timezone.now() + timedelta(days=7),
            source=Analysis.Source.DOCTOR_PRESCRIBED,
            status=Analysis.Status.PRESCRIBED,
        )

    def _url(self, action):
        return f"/api/v1/medical/analyses/{self.analysis.id}/{action}/"

    @patch("services.storage.head_object_or_none", side_effect=_fake_head_object)
    def test_submit_with_single_file_key_creates_analysisfile(self, _mock_head):
        """Eski single file_key payload — bitta AnalysisFile yaratiladi."""
        self.authenticate(self.patient)
        file_key = f"analyses/uploads/{self.patient.id}/abc123.jpg"
        resp = self.client.post(
            self._url("submit"),
            {
                "file_key": file_key,
                "file_mime": "image/jpeg",
                "patient_note": "Och qoringa topshirildi",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.analysis.refresh_from_db()
        self.assertEqual(self.analysis.status, Analysis.Status.SUBMITTED)
        self.assertIsNotNone(self.analysis.submitted_at)

        files = AnalysisFile.objects.filter(analysis=self.analysis)
        self.assertEqual(files.count(), 1)
        f = files.first()
        self.assertEqual(f.file_key, file_key)
        self.assertEqual(f.file_mime, "image/jpeg")
        self.assertEqual(f.uploaded_by_id, self.patient.id)

    @patch("services.storage.head_object_or_none", side_effect=_fake_head_object)
    def test_submit_accepts_result_upload_url_prefix(self, _mock_head):
        """Regression: result-upload-url/ per-analysis prefiks
        (analyses/{patient_id}/{analysis_id}/) submit'da qabul qilinsin — avval
        submit faqat analyses/uploads/ kutib 400 'Noto'g'ri file_key' bergan."""
        self.authenticate(self.patient)
        file_key = f"analyses/{self.patient.id}/{self.analysis.id}/result.pdf"
        resp = self.client.post(
            self._url("submit"),
            {"file_key": file_key, "file_mime": "application/pdf"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(
            AnalysisFile.objects.filter(
                analysis=self.analysis, file_key=file_key
            ).count(),
            1,
        )

    @patch("services.storage.head_object_or_none", side_effect=_fake_head_object)
    def test_submit_with_files_array_creates_multiple(self, _mock_head):
        """Yangi files[] payload — bir nechta AnalysisFile yaratiladi."""
        self.authenticate(self.patient)
        key_a = f"analyses/uploads/{self.patient.id}/a.jpg"
        key_b = f"analyses/uploads/{self.patient.id}/b.pdf"
        resp = self.client.post(
            self._url("submit"),
            {
                "files": [
                    {
                        "file_key": key_a,
                        "file_mime": "image/jpeg",
                        "original_name": "page1.jpg",
                    },
                    {
                        "file_key": key_b,
                        "file_mime": "application/pdf",
                        "original_name": "report.pdf",
                    },
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        files = AnalysisFile.objects.filter(analysis=self.analysis).order_by("order")
        self.assertEqual(files.count(), 2)
        self.assertEqual(files[0].file_key, key_a)
        self.assertEqual(files[0].order, 0)
        self.assertEqual(files[1].file_key, key_b)
        self.assertEqual(files[1].order, 1)
        self.assertEqual(files[1].original_name, "report.pdf")

    @patch("services.storage.head_object_or_none", side_effect=_fake_head_object)
    def test_resubmit_replaces_files(self, _mock_head):
        """Qayta submit qilganda eski fayllar almashtirilishi kerak."""
        self.authenticate(self.patient)
        old_key = f"analyses/uploads/{self.patient.id}/old.jpg"
        self.client.post(
            self._url("submit"),
            {"file_key": old_key, "file_mime": "image/jpeg"},
            format="json",
        )
        self.assertEqual(AnalysisFile.objects.filter(analysis=self.analysis).count(), 1)

        # Qayta yuborish — yangi 2 ta fayl bilan
        self.client.post(
            self._url("submit"),
            {
                "files": [
                    {"file_key": f"analyses/uploads/{self.patient.id}/new1.jpg"},
                    {"file_key": f"analyses/uploads/{self.patient.id}/new2.jpg"},
                ],
            },
            format="json",
        )

        files = AnalysisFile.objects.filter(analysis=self.analysis)
        self.assertEqual(files.count(), 2)
        # Eski fayl yo'q
        self.assertFalse(files.filter(file_key=old_key).exists())

    def test_submit_without_file_does_not_delete_existing_files(self):
        """Submit'da file berilmasa — eski fayllar tegilmasligi kerak.

        Frontend faqat patient_note yangilashi mumkin, fayl qaytarib yuklamasdan.
        """
        # Avval bir fayl yuklaymiz
        AnalysisFile.objects.create(
            analysis=self.analysis,
            file_key="analyses/1/2/existing.jpg",
            file_mime="image/jpeg",
            uploaded_by=self.patient,
        )
        self.authenticate(self.patient)
        resp = self.client.post(
            self._url("submit"),
            {"patient_note": "Faqat izoh yangilanyapti"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            AnalysisFile.objects.filter(analysis=self.analysis).count(),
            1,
            "files[] yoki file_key yuborilmagani uchun fayllar tegilmasligi shart",
        )

    @patch("services.storage.head_object_or_none", side_effect=_fake_head_object)
    def test_submit_response_includes_files(self, _mock_head):
        """Submit response AnalysisDetailSerializer qaytaradi — `files` to'la."""
        self.authenticate(self.patient)
        file_key = f"analyses/uploads/{self.patient.id}/test.pdf"
        resp = self.client.post(
            self._url("submit"),
            {"file_key": file_key, "file_mime": "application/pdf"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("files", resp.data)
        self.assertEqual(len(resp.data["files"]), 1)
        self.assertEqual(resp.data["files"][0]["file_key"], file_key)


class AnalysisCategoryTests(BaseAPITestCase):
    """Bug 2: type_category response'da, ?category= filter ishlaydi."""

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

        self.blood_type = _make_type("test-blood", "blood", "Qon")
        self.urine_type = _make_type("test-urine", "urine", "Siydik")

        # 2 ta qon analizi + 1 ta siydik analizi
        for _ in range(2):
            Analysis.objects.create(
                patient=self.patient,
                doctor=self.doctor_user,
                type=self.blood_type,
                deadline_at=timezone.now() + timedelta(days=5),
                status=Analysis.Status.PRESCRIBED,
            )
        Analysis.objects.create(
            patient=self.patient,
            doctor=self.doctor_user,
            type=self.urine_type,
            deadline_at=timezone.now() + timedelta(days=5),
            status=Analysis.Status.PRESCRIBED,
        )

    def test_my_returns_type_category_field(self):
        """Patient 'my' response'da `type_category` bo'lishi kerak."""
        self.authenticate(self.patient)
        resp = self.client.get("/api/v1/medical/analyses/my/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) > 0)
        for item in results:
            self.assertIn("type_category", item)
            self.assertIn(item["type_category"], ("blood", "urine"))

    def test_my_filter_by_category_blood(self):
        """`?category=blood` faqat qon analizlari qaytaradi."""
        self.authenticate(self.patient)
        resp = self.client.get("/api/v1/medical/analyses/my/?category=blood")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertEqual(len(results), 2)
        for item in results:
            self.assertEqual(item["type_category"], "blood")

    def test_my_filter_by_category_urine(self):
        """`?category=urine` faqat siydik analizlari qaytaradi."""
        self.authenticate(self.patient)
        resp = self.client.get("/api/v1/medical/analyses/my/?category=urine")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["type_category"], "urine")

    def test_doctor_list_filter_by_category(self):
        """Doctor list'da ham category filter ishlashi kerak."""
        self.authenticate(self.doctor_user)
        resp = self.client.get(
            f"/api/v1/medical/analyses/?patient_id={self.patient.id}&category=blood"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        results = resp.data.get("results", resp.data)
        self.assertEqual(len(results), 2)
        for item in results:
            self.assertEqual(item["type_category"], "blood")

    def test_analysis_types_full_returns_category(self):
        """`/medical/analysis-types/full/` javobida `category` bo'lishi kerak."""
        self.authenticate(self.patient)
        resp = self.client.get("/api/v1/medical/analysis-types/full/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        codes = {t["code"]: t for t in resp.data}
        self.assertIn("test-blood", codes)
        self.assertEqual(codes["test-blood"]["category"], "blood")
        self.assertEqual(codes["test-urine"]["category"], "urine")


class AnalysisTypeCategoryBackfillTests(BaseAPITestCase):
    """Migration backfill regression: yangi yaratilgan type default 'other'."""

    def test_default_category_is_other(self):
        atype = AnalysisType.objects.create(
            code="some-new-type",
            name={"uz": "Yangi"},
            is_active=True,
        )
        self.assertEqual(atype.category, "other")
