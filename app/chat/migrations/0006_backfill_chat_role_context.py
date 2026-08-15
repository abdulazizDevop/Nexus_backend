"""Existing chat data uchun yangi role-context fieldlarini backfill.

ChatRoom.patient va ChatRoom.doctor:
  - CONSULTATION room'larda: ikki participant'dan birida DoctorProfile
    bo'lsa — uni doctor sifatida olamiz, ikkinchisi patient bo'ladi
  - Topib bo'lmasa — None qoladi (legacy)

Message.sender_scope:
  - Sender DoctorProfile'ga ega va room'ning doctor'i shu user bo'lsa → "doctor"
  - Aks holda → "patient" (default)
  - Bu HEURISTIC — eski ma'lumot uchun aniq emas, lekin yangi kod uchun
    sender_scope JWT'dan to'g'ri yoziladi.

CallSession.caller_scope va callee_scope: bir xil heuristic.

Idempotent — qaytadan ishlatish xavfsiz (faqat null qiymatlarni to'ldiradi).
"""

from django.db import migrations


def backfill(apps, schema_editor):
    ChatRoom = apps.get_model("chat", "ChatRoom")
    Message = apps.get_model("chat", "Message")
    CallSession = apps.get_model("chat", "CallSession")
    DoctorProfile = apps.get_model("doctors", "DoctorProfile")
    Patient = apps.get_model("users", "Patient")

    rooms_filled = 0
    msgs_filled = 0
    calls_filled = 0

    for room in ChatRoom.objects.filter(patient__isnull=True, doctor__isnull=True):
        if room.room_type != "consultation":
            continue
        participants = list(room.participants.all())
        # Ikki participant'dan DoctorProfile bor bo'lganini topish
        doctor_profile = None
        patient_user = None
        for p in participants:
            dp = DoctorProfile.objects.filter(user=p).first()
            if dp and not doctor_profile:
                doctor_profile = dp
            else:
                patient_user = p

        if doctor_profile and patient_user:
            patient_profile = Patient.objects.filter(user=patient_user).first()
            if patient_profile:
                room.patient = patient_profile
                room.doctor = doctor_profile
                room.save(update_fields=["patient", "doctor"])
                rooms_filled += 1

    # Message scope — sender doctor bo'lsa "doctor", aks holda "patient"
    for msg in Message.objects.filter(sender_scope__isnull=True).select_related(
        "sender", "room__doctor"
    ):
        if msg.room.doctor_id and msg.room.doctor.user_id == msg.sender_id:
            msg.sender_scope = "doctor"
        else:
            # Default — patient (admin support'lar alohida — qoldiramiz)
            msg.sender_scope = "patient"
        msg.save(update_fields=["sender_scope"])
        msgs_filled += 1

    for call in CallSession.objects.filter(caller_scope__isnull=True).select_related(
        "caller", "callee", "room__doctor"
    ):
        room_doctor_user_id = call.room.doctor.user_id if call.room.doctor_id else None
        # Caller
        if room_doctor_user_id and call.caller_id == room_doctor_user_id:
            call.caller_scope = "doctor"
            call.callee_scope = "patient"
        elif room_doctor_user_id:
            call.caller_scope = "patient"
            call.callee_scope = "doctor"
        else:
            call.caller_scope = "patient"
            call.callee_scope = "patient"
        call.save(update_fields=["caller_scope", "callee_scope"])
        calls_filled += 1

    print(
        f"  → ChatRoom backfilled: {rooms_filled}, "
        f"Messages: {msgs_filled}, Calls: {calls_filled}"
    )


def reverse_backfill(apps, schema_editor):
    """Reverse migration — yangi field qiymatlarini null'ga qaytarish."""
    ChatRoom = apps.get_model("chat", "ChatRoom")
    Message = apps.get_model("chat", "Message")
    CallSession = apps.get_model("chat", "CallSession")

    ChatRoom.objects.update(patient=None, doctor=None)
    Message.objects.update(sender_scope=None)
    CallSession.objects.update(caller_scope=None, callee_scope=None)


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0005_add_scope_and_role_context"),
        ("doctors", "0008_remove_legacy_schedule"),
        ("users", "0008_backfill_patient_profiles"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
