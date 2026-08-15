from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


@shared_task(base=BaseTask, bind=True, name="chat.cleanup_old_deleted_messages")
def cleanup_old_deleted_messages(self):
    """30 kundan eski soft-deleted xabarlarni tozalaydi + DO Spaces fayllarini o'chiradi."""
    cutoff = timezone.now() - timedelta(days=30)

    # Faqat is_deleted=True bo'lganlarni — oddiy xabarlar saqlanib qoladi
    old_messages = Message.objects.filter(is_deleted=True, created_at__lt=cutoff)

    file_count = 0
    for msg in old_messages.filter(file_key__gt=""):
        delete_file(msg.file_key)
        file_count += 1

    total = old_messages.count()
    old_messages.delete()

    logger.info("Chat cleanup: %d xabar, %d fayl o'chirildi", total, file_count)


@shared_task(base=BaseTask, bind=True, name="chat.delete_file")
def delete_file_async(self, file_key):
    """S3 fayl o'chirish (Celery wrapper) — countdown bilan kechiktirib chaqirish
    uchun. `services.storage.delete_file` plain funksiya (task emas), shuning uchun
    `.apply_async(countdown=...)` ishlamasdi. Idempotent — fayl yo'q bo'lsa False."""
    return delete_file(file_key)


@shared_task(base=BaseTask, bind=True, name="chat.presence_offline_check")
def presence_offline_check(self, user_id):
    """Tarmoq uzilishidan ~TTL keyin chaqiriladi (PresenceConsumer.disconnect schedule).

    Agar user qayta ulangan bo'lsa (online flag hali tirik) — hech narsa qilmaydi
    (flap oldini olish). Aks holda (TTL tugagan, qayta ulanmagan) → chat-peer'larga
    offline broadcast. last_seen oxirgi heartbeat'дан (har heartbeat'да yangilanadi)."""
    if is_online(user_id):
        return  # qayta ulandi — online saqlanadi, broadcast shart emas

    last_seen = get_last_seen(user_id) or timezone.now().isoformat()
    layer = get_channel_layer()
    if layer is None:
        return
    for pid in chat_peer_ids(user_id):
        try:
            async_to_sync(layer.group_send)(
                f"presence_{pid}",
                {
                    "type": "presence.event",
                    "user_id": user_id,
                    "online": False,
                    "last_seen": last_seen,
                },
            )
        except Exception:
            pass  # channel layer o'chiq bo'lsa skip
