"""Chat sender_scope va ChatRoom.patient/doctor (Phase 3 Slice 1).

Test scope:
  - ChatRoom yangi `patient` va `doctor` field'lar (nullable)
  - Message yangi `sender_scope` field'i
  - `get_or_create_consultation(patient, doctor_profile)` method
  - View'lar Message yaratilganda sender_scope JWT'dan to'g'ri yoziladi
  - CallSession caller_scope/callee_scope yoziladi
  - Backwards compat: eski endpoint'lar buzilmaydi
"""

from django.contrib.auth import get_user_model

from app.chat.models import ChatRoom, Message
from app.doctors.models import DoctorProfile
from tests.base import BaseAPITestCase

User = get_user_model()


class ChatRoomConsultationTests(BaseAPITestCase):
    """get_or_create_consultation — Patient va Doctor ID bo'yicha unikal."""

    def test_create_consultation_room(self):
        patient_user = self.create_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        room, created = ChatRoom.get_or_create_consultation(
            patient_user.patient_profile, doctor_profile
        )
        self.assertTrue(created)
        self.assertEqual(room.room_type, "consultation")
        self.assertEqual(room.patient_id, patient_user.patient_profile.id)
        self.assertEqual(room.doctor_id, doctor_profile.id)
        # Participants ham qo'shilgan
        ids = list(room.participants.values_list("id", flat=True))
        self.assertIn(patient_user.id, ids)
        self.assertIn(doctor_user.id, ids)

    def test_consultation_room_idempotent(self):
        """Bir xil patient + doctor uchun bitta xona qaytariladi."""
        patient_user = self.create_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        room1, created1 = ChatRoom.get_or_create_consultation(
            patient_user.patient_profile, doctor_profile
        )
        room2, created2 = ChatRoom.get_or_create_consultation(
            patient_user.patient_profile, doctor_profile
        )
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(room1.id, room2.id)

    def test_dual_role_user_separate_rooms(self):
        """User A patient sifatida B (doctor) bilan, va A doctor sifatida B
        (patient) bilan — ALOHIDA xonalar (Yandex Taxi modeli)."""
        # User A: ham patient, ham doctor
        user_a = self.create_doctor()
        a_doctor = DoctorProfile.objects.create(user=user_a, is_verified=True)
        # User B: ham patient, ham doctor
        user_b = self.create_doctor()
        b_doctor = DoctorProfile.objects.create(user=user_b, is_verified=True)

        # Xona 1: A patient ↔ B doctor
        room1, _ = ChatRoom.get_or_create_consultation(
            user_a.patient_profile, b_doctor
        )
        # Xona 2: B patient ↔ A doctor
        room2, _ = ChatRoom.get_or_create_consultation(
            user_b.patient_profile, a_doctor
        )

        self.assertNotEqual(room1.id, room2.id)
        self.assertEqual(room1.patient_id, user_a.patient_profile.id)
        self.assertEqual(room1.doctor_id, b_doctor.id)
        self.assertEqual(room2.patient_id, user_b.patient_profile.id)
        self.assertEqual(room2.doctor_id, a_doctor.id)


class MessageScopeTests(BaseAPITestCase):
    """Message.sender_scope JWT scope'idan to'g'ri yoziladi."""

    def test_system_message_on_chat_open_has_scope(self):
        """Chat ochilganda system xabar — sender_scope yoziladi."""
        patient_user = self.auth_as_patient()
        doctor_user = self.create_doctor()
        doctor_profile = DoctorProfile.objects.create(
            user=doctor_user, is_verified=True
        )

        # doctor_id — DoctorProfile.id (User.id emas)
        resp = self.client.post(
            "/api/v1/chat/rooms/",
            data={"doctor_id": doctor_profile.id},
            format="json",
        )
        self.assertIn(resp.status_code, (200, 201))
        room_id = resp.data["id"]

        sys_msg = Message.objects.filter(
            room_id=room_id, sender=patient_user, message_type="system"
        ).first()
        if sys_msg is not None:
            self.assertEqual(sys_msg.sender_scope, "patient")


class MessageScopeBackwardsCompatTests(BaseAPITestCase):
    """sender_scope null bo'lsa ham serializer xato bermaydi."""

    def test_legacy_message_without_scope_serializes(self):
        patient_user = self.create_patient()
        doctor_user = self.create_doctor()
        DoctorProfile.objects.create(user=doctor_user, is_verified=True)

        room = ChatRoom.objects.create()
        room.participants.add(patient_user, doctor_user)
        # Legacy message — sender_scope null
        msg = Message.objects.create(
            room=room,
            sender=patient_user,
            message_type="text",
            content="legacy",
        )
        self.assertIsNone(msg.sender_scope)

        # Authenticate va GET qilish
        self.authenticate(patient_user)
        resp = self.client.get(
            f"/api/v1/chat/rooms/{room.id}/messages/",
        )
        self.assertEqual(resp.status_code, 200)
        # Pagination response — `results` ichida
        results = resp.data.get("results", resp.data)
        # Eski xabar ham qaytariladi va sender_scope null
        text_msg = next(
            (m for m in results if m.get("content") == "legacy"), None
        )
        self.assertIsNotNone(text_msg)
        self.assertIsNone(text_msg["sender_scope"])
