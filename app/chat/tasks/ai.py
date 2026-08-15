from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


# --- AI gatekeeper: tarifsiz bemorga avto-javob ---


def _build_chat_ai_history(room, patient_user_id, exclude_id, limit):
    """Room'ning oxirgi text xabarlarini Gemini formatiga o'giradi.

    Bemor xabari → "user", AI/doctor xabari → "model".
    """
    msgs = list(
        reversed(
            list(
                Message.objects.filter(
                    room=room,
                    is_deleted=False,
                    message_type=Message.MessageType.TEXT,
                )
                .exclude(id=exclude_id)
                .order_by("-created_at")[:limit]
            )
        )
    )
    history = []
    for m in msgs:
        if not m.content:
            continue
        is_patient = (m.sender_id == patient_user_id) and not m.is_ai
        history.append({"role": "user" if is_patient else "model", "text": m.content})
    return history


def _broadcast_ai_message(room_id, ai_msg, doctor_user, doctor_profile):
    """AI xabarni WS group'ga _save_message bilan bir xil shaklda yuboradi (+is_ai)."""
    message = {
        "id": ai_msg.id,
        "sender": {
            "id": doctor_user.id,
            "patient_profile_id": None,
            "doctor_profile_id": doctor_profile.id,
            "full_name": doctor_user.full_name,
            "avatar": generate_download_url(doctor_user.avatar) if doctor_user.avatar else None,
            "role": doctor_user.role,
            "admin_type": getattr(doctor_user, "admin_type", None),
        },
        "sender_name": doctor_user.full_name,
        "sender_role": doctor_user.role,
        "sender_scope": ai_msg.sender_scope,
        "sender_admin_type": getattr(doctor_user, "admin_type", None),
        "message_type": ai_msg.message_type,
        "content": ai_msg.content,
        "file_key": "",
        "file_name": "",
        "file_size": None,
        "file_type": "",
        "audio_status": None,
        "reply_to": ai_msg.reply_to_id,
        "is_read": False,
        "is_ai": True,
        "created_at": ai_msg.created_at.isoformat(),
    }
    async_to_sync(get_channel_layer().group_send)(
        f"chat_{room_id}",
        {"type": "chat.new_message", "message": message},
    )


def _save_ai_message(room, doctor, content, reply_to):
    """AI xabarni saqlaydi (sender=doctor, is_ai=True) + broadcast + bemorga push."""
    ai_msg = Message.objects.create(
        room=room,
        sender=doctor.user,
        sender_scope=Message.SenderScope.DOCTOR,
        message_type=Message.MessageType.TEXT,
        content=content,
        is_ai=True,
        reply_to=reply_to,
    )
    room.updated_at = timezone.now()
    room.save(update_fields=["updated_at"])
    _broadcast_ai_message(room.id, ai_msg, doctor.user, doctor)
    # sender=doctor → notification task faqat bemorga push qiladi (doctor emas).
    send_new_message_notification.delay(ai_msg.id)
    return ai_msg


@shared_task(base=BaseTask, bind=True, name="chat.generate_ai_reply")
def generate_chat_ai_reply(self, room_id, trigger_message_id):
    """Tarifsiz bemor xabariga AI javob yaratadi (umumiy javob + kontekstli upsell)."""
    from app.chat.ai.constants import CHAT_AI_HISTORY_LIMIT
    from app.chat.ai.context import build_patient_context
    from app.chat.ai.gate import (
        get_sellable_tariffs,
        increment_chat_ai_usage,
        should_ai_handle,
        under_cap,
    )
    from app.chat.ai.prompts import build_chat_ai_system_prompt
    from app.diet_ai.guardrails import get_safety_response, is_dangerous
    from services.gemini import generate_text

    try:
        trigger = Message.objects.select_related(
            "room",
            "room__patient__user",
            "room__doctor__user",
            "room__doctor__specialty",
            "sender",
        ).get(id=trigger_message_id)
    except Message.DoesNotExist:
        return

    room = trigger.room

    # Idempotency: bu trigger uchun AI javob allaqachon bormi (Celery redelivery).
    if Message.objects.filter(room=room, is_ai=True, reply_to_id=trigger.id).exists():
        return

    # Loop/re-gate: faqat bemor text xabari, AI emas, room aktiv.
    if trigger.is_ai or trigger.sender_scope != "patient" or not trigger.content:
        return
    if not room.is_active:
        return

    patient_user = room.patient.user if room.patient_id else trigger.sender
    allowed, doctor = should_ai_handle(room, patient_user, "patient")
    if not allowed:
        return
    if not under_cap(patient_user, doctor):
        return  # cap tugadi — silent

    lang = getattr(getattr(patient_user, "settings", None), "language", None) or "uz"

    # Xavfli mavzu → xavfsizlik javobi (cap'ga sanalmaydi).
    dangerous, _reason = is_dangerous(trigger.content)
    if dangerous:
        _save_ai_message(room, doctor, get_safety_response(lang), trigger)
        return

    tariffs = list(get_sellable_tariffs(doctor)[:3])
    if not tariffs:
        return

    patient_context = build_patient_context(patient_user)
    system_prompt = build_chat_ai_system_prompt(lang, patient_context, doctor, tariffs)
    history = _build_chat_ai_history(
        room, patient_user.id, trigger.id, CHAT_AI_HISTORY_LIMIT
    )

    result = generate_text(
        prompt=trigger.content,
        system_instruction=system_prompt,
        history=history,
        temperature=0.6,
    )
    if "error" in result or not result.get("text"):
        logger.warning(
            "Chat AI reply error room=%s: %s", room.id, result.get("error")
        )
        return  # silent — buzuq bubble yo'q, usage oshmaydi

    _save_ai_message(room, doctor, result["text"], trigger)
    increment_chat_ai_usage(
        patient_user,
        doctor,
        result.get("tokens_input", 0),
        result.get("tokens_output", 0),
    )


