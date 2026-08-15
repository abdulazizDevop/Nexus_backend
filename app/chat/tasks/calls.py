from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


@shared_task(base=BaseTask, bind=True, name="chat.check_missed_call")
def check_missed_call(self, call_session_id):
    """60 soniyadan keyin hali ringing bo'lsa → missed."""
    try:
        session = CallSession.objects.select_related("caller", "room").get(
            id=call_session_id
        )
    except CallSession.DoesNotExist:
        return

    if session.status != CallSession.Status.RINGING:
        return  # allaqachon javob berilgan

    session.status = CallSession.Status.MISSED
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at"])

    # System message
    Message.create_system(
        session.room,
        session.system_message_missed(),
        sender=session.caller,
        scope=session.caller_scope,
    )

    # WebSocket: caller'ga call_missed
    try:
        async_to_sync(get_channel_layer().group_send)(
            f"chat_{session.room_id}",
            {
                "type": "call.event",
                "event": "call_missed",
                "call_session_id": session.id,
            },
        )
    except Exception:
        pass

    # Notification + push: caller'ga "Javobsiz"
    try:
        notify_by_key_user.delay(
            user_id=session.caller_id,
            type=Notification.Type.CALL_MISSED,
            key="missed_call",
            params={"name": session.callee.full_name or "Foydalanuvchi"},
            data={
                "call_session_id": str(session.id),
                "room_id": str(session.room_id),
            },
            app_scope=session.caller_scope or None,
        )
    except Exception:
        pass

    # Callee qurilmasiga cancel push — kechikkan push "arvoh qo'ng'iroq"
    # ko'rsatmasligi / CallKit jiringlab qolmasligi uchun (ISH-4).
    _send_call_cancel_push(session)

    logger.info("Call #%s missed (60s timeout)", call_session_id)


def _send_call_cancel_push(session):
    """Callee qurilmasiga data-only `call_cancelled` push — CallKit/incoming UI'ni
    yopish uchun (caller bekor qildi yoki timeout). app_scope=callee_scope bo'yicha
    faqat to'g'ri app'ga boradi (cross-app leak yo'q)."""
    try:
        send_push_to_user.delay(
            user_id=session.callee_id,
            title="",
            body="",
            data={
                "type": "call_cancelled",
                "call_session_id": str(session.id),
                "room_id": str(session.room_id),
            },
            data_only=True,
            app_scope=session.callee_scope or None,
        )
    except Exception:
        pass


@shared_task(base=BaseTask, bind=True, name="chat.check_unreachable_call")
def check_unreachable_call(self, call_session_id):
    """Call initiate'dan 20s — callee qurilmasiga yetmadi (ringing_at yo'q) →
    MISSED + caller'ga `call_failed{unreachable}`.

    Telegram-uslubidagi delivery-ack: qurilma incoming UI ko'rsatganda
    `POST .../call/ringing/` ack yuboradi (ringing_at). Ack kelmasa — bemor
    yetib bo'lmas holatda (telefon o'chiq / internet yo'q), doctor cheksiz
    kutmasin."""
    try:
        session = CallSession.objects.select_related("caller", "callee", "room").get(
            id=call_session_id
        )
    except CallSession.DoesNotExist:
        return

    if session.status != CallSession.Status.RINGING:
        return  # allaqachon accept/reject/end
    if session.ringing_at is not None:
        return  # qurilmaga yetdi — 60s check_missed_call o'z ishini qiladi

    session.status = CallSession.Status.MISSED
    session.ended_at = timezone.now()
    session.save(update_fields=["status", "ended_at"])

    Message.create_system(
        session.room,
        session.system_message_missed(),
        sender=session.caller,
        scope=session.caller_scope,
    )

    # WebSocket: caller'ga call_failed{unreachable} — UI "yetib bo'lmadi" dialog
    try:
        async_to_sync(get_channel_layer().group_send)(
            f"chat_{session.room_id}",
            {
                "type": "call.event",
                "event": "call_failed",
                "call_session_id": session.id,
                "reason": "unreachable",
            },
        )
    except Exception:
        pass

    try:
        notify_by_key_user.delay(
            user_id=session.caller_id,
            type=Notification.Type.CALL_MISSED,
            key="missed_call",
            params={"name": session.callee.full_name or "Foydalanuvchi"},
            data={
                "call_session_id": str(session.id),
                "room_id": str(session.room_id),
            },
            app_scope=session.caller_scope or None,
        )
    except Exception:
        pass

    # Kechikkan push race'i uchun callee'ga cancel push (ISH-4)
    _send_call_cancel_push(session)

    logger.info("Call #%s unreachable (20s, no ack)", call_session_id)


