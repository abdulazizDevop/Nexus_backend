from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


def _resolve_chat_scope(room, user) -> str | None:
    """Recipient shu chat xonasida qaysi rol sifatida turibdi — push qaysi app'ga.

    Bitta phone Patient va Doctor sifatida ham login bo'lsa, xabar faqat
    suhbatdosh ko'rib turgan app'ga borishi kerak.
    """
    if room.room_type == ChatRoom.RoomType.CONSULTATION:
        if room.patient_id and room.patient.user_id == user.id:
            return "patient"
        if room.doctor_id and room.doctor.user_id == user.id:
            return "doctor"
        # Eski (Patient/Doctor FK to'ldirilmagan) xonalar — recipient.role'ga qaytamiz
        return getattr(user, "active_role", None) or getattr(user, "role", None)

    if room.room_type == ChatRoom.RoomType.SUPPORT:
        return getattr(user, "role", None)

    return None


@shared_task(base=BaseTask, bind=True, name="chat.send_new_message_notification")
def send_new_message_notification(self, message_id):
    """Chat xabari kelganda push yuboradi.

    "Shu chatni ochib o'tirgan" UX qarori — banner'ni yashirish kerak yoki
    yo'qligini client (activeChatRoomNotifier) hal qiladi. Backend WebSocket
    online flag'iga qarab push'ni skip qilmaydi.
    """
    try:
        msg = Message.objects.select_related("sender", "room").get(id=message_id)
    except Message.DoesNotExist:
        return

    recipients = list(msg.room.participants.exclude(id=msg.sender_id))

    # Support chat'da admin participant emas — adminlarga ham push kerak
    if msg.room.room_type == ChatRoom.RoomType.SUPPORT and msg.sender.role != User.Role.ADMIN:
        admin_ids = {r.id for r in recipients}
        admins = User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(
            id__in=admin_ids | {msg.sender_id}
        )
        recipients.extend(admins)

    preview = msg.content[:100] if msg.content else f"[{msg.get_message_type_display()}]"
    sender_name = msg.sender.full_name or "Yangi xabar"

    # Support room xabari feed'da doctor chatidan AJRALISHI shart — mobil
    # tap->support-chat routing notification `type`'iga qarab ishlaydi. REST
    # admin-reply yo'li allaqachon SUPPORT_MESSAGE beradi; WS yo'lini ham moslaymiz
    # (aks holda WS orqali kelgan support xabari feed'da CHAT_MESSAGE bo'lib qolardi).
    notif_type = (
        Notification.Type.SUPPORT_MESSAGE
        if msg.room.room_type == ChatRoom.RoomType.SUPPORT
        else Notification.Type.CHAT_MESSAGE
    )

    for recipient in recipients:
        # Recipient shu xonada qaysi rol sifatida turibdi — shu app'ga push:
        #   consultation: room.patient.user_id == recipient.id → patient app
        #                 room.doctor.user.id  == recipient.id → doctor app
        #   support:      admin → admin; oddiy user → role/active_role
        recipient_scope = _resolve_chat_scope(msg.room, recipient)
        try:
            notify(
                recipient,
                type=notif_type,
                title=sender_name,
                body=preview,
                data={
                    "room_id": str(msg.room_id),
                    "message_id": str(msg.id),
                    "sender_id": str(msg.sender_id),  # client bump/dedupe uchun
                },
                app_scope=recipient_scope,
            )
        except Exception:
            logger.exception("Chat notification xatosi")

    logger.info("Chat notification yuborildi: message #%s", message_id)


