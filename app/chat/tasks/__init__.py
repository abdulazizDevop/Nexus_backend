"""chat task'lari — modullarga bo'lingan (import yo'llari + Celery task nomlari o'zgarmaydi).

`from app.chat.tasks import X` ishlashda davom etadi (consumers, views, utils).
Bu __init__ barcha @shared_task funksiyani import qiladi — Celery autodiscovery
ularni ro'yxatga oladi (name= aniq berilgan, joyi o'zgargani ta'sir qilmaydi).
"""

from .ai import generate_chat_ai_reply
from .calls import (
    _send_call_cancel_push,
    check_missed_call,
    check_unreachable_call,
)
from .maintenance import (
    cleanup_old_deleted_messages,
    delete_file_async,
    presence_offline_check,
)
from .notifications import send_new_message_notification
from .transcode import transcode_voice_message

__all__ = [
    "send_new_message_notification",
    "generate_chat_ai_reply",
    "check_missed_call",
    "check_unreachable_call",
    "_send_call_cancel_push",
    "cleanup_old_deleted_messages",
    "delete_file_async",
    "presence_offline_check",
    "transcode_voice_message",
]
