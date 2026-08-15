from .common import *  # noqa: F401,F403


def _do_broadcast(
    user_ids: list[int],
    title: str,
    body: str,
    send_push: bool = True,
    send_sys_msg: bool = False,
    app_scope: str | None = None,
    sender_id: int | None = None,
) -> dict:
    """Admin broadcast yadrosi — Notification + push + system message.

    Celery task (katta auditoriya, async) ham, view (kichik auditoriya, sinxron —
    admin push natijasini DARHOL ko'rsin) ham shu funksiyani chaqiradi.
    Notification + system message atomik; push best-effort (xatosi DB'ni bekor qilmaydi).
    """
    target_users = list(User.objects.filter(id__in=user_ids, is_active=True))
    if not target_users:
        return {"target_users": 0, "push_sent": 0, "push_failed": 0, "system_messages_sent": 0}

    btype = Notification.Type.ADMIN_BROADCAST
    data = {"type": btype.value}

    sys_msg_count = 0
    with transaction.atomic():
        Notification.objects.bulk_create(
            [
                Notification(
                    user=u,
                    type=btype,
                    title=title,
                    body=body,
                    data=data,
                )
                for u in target_users
            ]
        )

        if send_sys_msg:
            sys_msg_count = _broadcast_system_messages(target_users, title, body, sender_id)

    push_result = {"success_count": 0, "failure_count": 0}
    if send_push:
        try:
            push_result = send_to_users(
                target_users, title, body, data, app_scope=app_scope
            )
        except Exception:
            logger.exception("Broadcast push xatosi (DB yozuvlar saqlandi)")

    result = {
        "target_users": len(target_users),
        "push_sent": push_result.get("success_count", 0),
        "push_failed": push_result.get("failure_count", 0),
        "system_messages_sent": sys_msg_count,
    }
    logger.info("Admin broadcast natijasi: %s", result)
    return result


@shared_task(base=BaseTask, bind=True, name="notifications.run_admin_broadcast")
def run_admin_broadcast(
    self,
    user_ids: list[int],
    title: str,
    body: str,
    send_push: bool = True,
    send_sys_msg: bool = False,
    app_scope: str | None = None,
    sender_id: int | None = None,
):
    """Katta auditoriya uchun async wrapper (HTTP thread'ni bloklamaydi)."""
    return _do_broadcast(
        user_ids, title, body, send_push, send_sys_msg, app_scope, sender_id
    )


def _broadcast_system_messages(target_users, title, body, sender_id) -> int:
    """Har bir userning SUPPORT chat xonasiga system message yozadi.

    Mavjud support room'larni bitta query bilan oladi, faqat yo'qlarini yaratadi,
    so'ng Message'larni bulk_create qiladi.
    """
    from app.chat.models import ChatRoom, Message

    user_ids = [u.id for u in target_users]

    # Mavjud support xonalar (user -> room) bitta query bilan
    rooms_by_user: dict[int, ChatRoom] = {}
    existing = (
        ChatRoom.objects.filter(
            room_type=ChatRoom.RoomType.SUPPORT,
            participants__id__in=user_ids,
        )
        .prefetch_related("participants")
        .distinct()
    )
    for room in existing:
        for participant in room.participants.all():
            if participant.id in user_ids:
                rooms_by_user.setdefault(participant.id, room)

    # Yo'q userlar uchun yangi support xona
    for user in target_users:
        if user.id not in rooms_by_user:
            room = ChatRoom.objects.create(room_type=ChatRoom.RoomType.SUPPORT)
            room.participants.add(user)
            rooms_by_user[user.id] = room

    content = f"📢 {title}\n{body}"
    Message.objects.bulk_create(
        [
            Message(
                room=rooms_by_user[user.id],
                sender_id=sender_id,
                message_type=Message.MessageType.SYSTEM,
                content=content,
            )
            for user in target_users
        ]
    )
    return len(target_users)
