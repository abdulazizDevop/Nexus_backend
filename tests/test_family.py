"""Family app — oila a'zosi kuzatuvi testlari."""

from rest_framework import status

from app.family.models import FamilyLink
from tests.base import BaseAPITestCase


class FamilyInviteTests(BaseAPITestCase):
    """Taklif → qabul/rad → bekor oqimi"""

    def test_invite_by_phone_creates_pending_link(self):
        """POST /family/members/invite/ — pending link yaratadi"""
        member = self.create_patient(phone="998901112233")
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/family/members/invite/",
            {"phone": "998901112233", "relation": "child"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertEqual(resp.data["status"], "pending")
        self.assertEqual(resp.data["member"], member.id)

    def test_invite_unknown_phone_404(self):
        """POST invite — ro'yxatdan o'tmagan raqam → 404"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/family/members/invite/",
            {"phone": "998900000001", "relation": "child"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_invite_self_rejected(self):
        """POST invite — o'zini qo'shish mumkin emas"""
        me = self.auth_as_patient(phone="998905555555")
        resp = self.client.post(
            "/api/v1/family/members/invite/",
            {"phone": me.phone, "relation": "other"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_member_accepts_invitation(self):
        """POST /family/me/{id}/accept/ — a'zo taklifni qabul qiladi"""
        patient = self.create_patient()
        member = self.create_patient(phone="998901112244")
        link = FamilyLink.objects.create(patient=patient, member=member)

        self.authenticate(member)
        resp = self.client.post(f"/api/v1/family/me/{link.id}/accept/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        link.refresh_from_db()
        self.assertEqual(link.status, FamilyLink.Status.ACCEPTED)
        self.assertIsNotNone(link.responded_at)

    def test_member_declines_invitation(self):
        """POST /family/me/{id}/decline/ — rad etish"""
        patient = self.create_patient()
        member = self.create_patient(phone="998901112255")
        link = FamilyLink.objects.create(patient=patient, member=member)

        self.authenticate(member)
        resp = self.client.post(f"/api/v1/family/me/{link.id}/decline/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        link.refresh_from_db()
        self.assertEqual(link.status, FamilyLink.Status.DECLINED)

    def test_patient_revokes_link(self):
        """DELETE /family/members/{id}/ — bemor a'zoni chiqaradi"""
        member = self.create_patient(phone="998901112266")
        patient = self.auth_as_patient()
        link = FamilyLink.objects.create(
            patient=patient, member=member, status=FamilyLink.Status.ACCEPTED
        )
        resp = self.client.delete(f"/api/v1/family/members/{link.id}/")
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        link.refresh_from_db()
        self.assertEqual(link.status, FamilyLink.Status.REVOKED)

    def test_reinvite_after_decline_resets_to_pending(self):
        """Rad etilgan a'zoni qayta taklif qilish — pending'ga qaytadi"""
        member = self.create_patient(phone="998901112277")
        patient = self.auth_as_patient()
        FamilyLink.objects.create(
            patient=patient, member=member, status=FamilyLink.Status.DECLINED
        )
        resp = self.client.post(
            "/api/v1/family/members/invite/",
            {"phone": member.phone, "relation": "parent"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["status"], "pending")


class FamilyAccessTests(BaseAPITestCase):
    """A'zoning bemor ma'lumotlariga kirishi"""

    def _linked_pair(self, status_=FamilyLink.Status.ACCEPTED):
        patient = self.create_patient(phone="998907770001")
        member = self.create_patient(phone="998907770002")
        FamilyLink.objects.create(patient=patient, member=member, status=status_)
        return patient, member

    def test_member_sees_tracked_patients(self):
        """GET /family/me/patients/ — ACCEPTED bemorlar ro'yxati"""
        patient, member = self._linked_pair()
        self.authenticate(member)
        resp = self.client.get("/api/v1/family/me/patients/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["patient"], patient.id)

    def test_member_gets_daily_report(self):
        """GET /family/patients/{id}/daily-report/ — ACCEPTED a'zo o'qiy oladi"""
        patient, member = self._linked_pair()
        self.authenticate(member)
        resp = self.client.get(f"/api/v1/family/patients/{patient.id}/daily-report/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(resp.data["patient_id"], patient.id)
        self.assertIn("treatments", resp.data)
        self.assertIn("indicators", resp.data)

    def test_pending_member_cannot_get_daily_report(self):
        """PENDING holatda daily-report yopiq (403)"""
        patient, member = self._linked_pair(status_=FamilyLink.Status.PENDING)
        self.authenticate(member)
        resp = self.client.get(f"/api/v1/family/patients/{patient.id}/daily-report/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_stranger_cannot_get_daily_report(self):
        """Bog'lanmagan user uchun 403"""
        patient = self.create_patient(phone="998907770003")
        self.auth_as_patient()
        resp = self.client.get(f"/api/v1/family/patients/{patient.id}/daily-report/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
