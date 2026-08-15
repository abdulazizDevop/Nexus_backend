from django.utils import timezone

from rest_framework import status

from tests.base import BaseAPITestCase


class UserProfileTests(BaseAPITestCase):
    """Users — /me/ profil endpointlar"""

    def test_me_get_success(self):
        """GET /users/me/ — o'z profilini olish"""
        user = self.auth_as_patient(full_name="Test User")
        resp = self.client.get("/api/v1/users/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["full_name"], "Test User")
        self.assertIn("settings", resp.data)

    def test_me_unauthenticated(self):
        """GET /users/me/ — login qilmagan"""
        resp = self.client.get("/api/v1/users/me/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_patch_success(self):
        """PATCH /users/me/ — profilni yangilash"""
        self.auth_as_patient()
        resp = self.client.patch(
            "/api/v1/users/me/",
            {
                "full_name": "Yangi Ism",
                "sex": "male",
            },
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["full_name"], "Yangi Ism")

    def test_me_patch_with_settings(self):
        """PATCH /users/me/ — settings bilan birga yangilash"""
        self.auth_as_patient()
        resp = self.client.patch(
            "/api/v1/users/me/",
            {"settings": {"language": "en", "theme": "dark"}},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class ChangeRoleTests(BaseAPITestCase):
    """Users — change-role (faqat Super Admin)"""

    def test_change_role_success(self):
        """PATCH /users/{id}/change-role/ — Super Admin rol o'zgartiradi"""
        self.auth_as_admin(admin_type="super")
        patient = self.create_patient()
        resp = self.client.patch(
            f"/api/v1/users/{patient.id}/change-role/",
            {"role": "doctor"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        patient.refresh_from_db()
        self.assertEqual(patient.role, "doctor")

    def test_change_role_to_admin_requires_type(self):
        """PATCH /users/{id}/change-role/ — admin ga o'zgartishda admin_type kerak"""
        self.auth_as_admin(admin_type="super")
        patient = self.create_patient()
        resp = self.client.patch(
            f"/api/v1/users/{patient.id}/change-role/",
            {"role": "admin"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_role_non_admin_forbidden(self):
        """PATCH /users/{id}/change-role/ — oddiy user uchun 403"""
        self.auth_as_patient()
        other = self.create_patient()
        resp = self.client.patch(
            f"/api/v1/users/{other.id}/change-role/",
            {"role": "doctor"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_change_role_simple_admin_forbidden(self):
        """PATCH /users/{id}/change-role/ — simple admin ham ruxsatsiz"""
        self.auth_as_admin(admin_type="simple")
        patient = self.create_patient()
        resp = self.client.patch(
            f"/api/v1/users/{patient.id}/change-role/",
            {"role": "doctor"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class LinkDoctorTests(BaseAPITestCase):
    """Users — doctorga bog'lanish"""

    def test_link_doctor_success(self):
        """POST /users/me/link-doctor/ — referral code bilan"""
        self.auth_as_patient()
        doctor = self.create_doctor()
        resp = self.client.post(
            "/api/v1/users/me/link-doctor/",
            {"referral_code": doctor.referral_code},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_link_doctor_invalid_code(self):
        """POST /users/me/link-doctor/ — noto'g'ri referral code"""
        self.auth_as_patient()
        resp = self.client.post(
            "/api/v1/users/me/link-doctor/",
            {"referral_code": "INVALID1"},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_my_doctors_success(self):
        """GET /users/me/my-doctors/ — o'ziga birikkan doktorlar"""
        patient = self.auth_as_patient()
        doctor = self.create_doctor()
        patient.referred_by = doctor
        patient.save(update_fields=["referred_by"])

        resp = self.client.get("/api/v1/users/me/my-doctors/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class MyDoctorsChatOrderingTests(BaseAPITestCase):
    """GET /users/me/my-doctors/ — chat activity bo'yicha tartib + unread_count"""

    def _setup(self):
        from datetime import timedelta

        from app.chat.models import ChatRoom, Message
        from app.doctors.models import DoctorPatient, DoctorProfile

        patient = self.auth_as_patient()
        patient_profile = patient.patient_profile

        # 3 ta doctor — DoctorProfile + ACCEPTED bog'lanish bilan
        doctors = []
        for i in range(3):
            doc_user = self.create_doctor(full_name=f"Doc {i}")
            profile = DoctorProfile.objects.create(user=doc_user, is_verified=True)
            DoctorPatient.objects.create(
                doctor=profile,
                patient=patient,
                status=DoctorPatient.Status.ACCEPTED,
                added_by=DoctorPatient.AddedBy.PATIENT,
            )
            doctors.append((doc_user, profile))

        # Doc0 — eski chat (1 soat oldin), o'qilgan
        room0 = ChatRoom.objects.create(
            room_type=ChatRoom.RoomType.CONSULTATION,
            patient=patient_profile,
            doctor=doctors[0][1],
        )
        room0.participants.add(patient, doctors[0][0])
        Message.objects.create(
            room=room0, sender=doctors[0][0], content="salom", is_read=True
        )
        ChatRoom.objects.filter(pk=room0.pk).update(
            updated_at=timezone.now() - timedelta(hours=1)
        )

        # Doc1 — yangi chat (hozir), 2 ta o'qilmagan xabar doctor'dan
        room1 = ChatRoom.objects.create(
            room_type=ChatRoom.RoomType.CONSULTATION,
            patient=patient_profile,
            doctor=doctors[1][1],
        )
        room1.participants.add(patient, doctors[1][0])
        for _ in range(2):
            Message.objects.create(
                room=room1, sender=doctors[1][0], content="?", is_read=False
            )
        # Patient o'zi yuborgan xabar — unread_count ga kirmasligi kerak
        Message.objects.create(
            room=room1, sender=patient, content="javob", is_read=False
        )
        # O'chirilgan xabar — kirmasligi kerak
        Message.objects.create(
            room=room1,
            sender=doctors[1][0],
            content="del",
            is_read=False,
            is_deleted=True,
        )

        # Doc2 — chat yo'q

        return patient, doctors

    def test_ordering_by_chat_recency(self):
        """Yangi xabarli doctor tepada, chat'sizlar pastda."""
        _, doctors = self._setup()
        resp = self.client.get("/api/v1/users/me/my-doctors/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        ids = [d["user_id"] for d in resp.data]
        # doc1 (yangi chat) → doc0 (eski chat) → doc2 (chat yo'q)
        self.assertEqual(ids[0], doctors[1][0].id)
        self.assertEqual(ids[1], doctors[0][0].id)
        self.assertEqual(ids[2], doctors[2][0].id)

    def test_unread_count(self):
        """Faqat boshqa tomon yuborgan, o'qilmagan, o'chirilmagan xabarlar sanaladi."""
        _, doctors = self._setup()
        resp = self.client.get("/api/v1/users/me/my-doctors/")
        by_user = {d["user_id"]: d for d in resp.data}

        self.assertEqual(by_user[doctors[1][0].id]["unread_count"], 2)
        self.assertEqual(by_user[doctors[0][0].id]["unread_count"], 0)
        self.assertEqual(by_user[doctors[2][0].id]["unread_count"], 0)

    def test_last_chat_at_present(self):
        """last_chat_at — chat bor doctorda dolzarb, chat yo'qda null."""
        _, doctors = self._setup()
        resp = self.client.get("/api/v1/users/me/my-doctors/")
        by_user = {d["user_id"]: d for d in resp.data}

        self.assertIsNotNone(by_user[doctors[1][0].id]["last_chat_at"])
        self.assertIsNotNone(by_user[doctors[0][0].id]["last_chat_at"])
        self.assertIsNone(by_user[doctors[2][0].id]["last_chat_at"])
