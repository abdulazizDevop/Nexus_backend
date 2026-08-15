import logging

from celery import shared_task

from core.tasks import BaseTask
from services.telegram import delete_telegram_message

logger = logging.getLogger(__name__)


@shared_task(base=BaseTask, bind=True, name="auth.delete_otp_telegram_message")
def delete_otp_telegram_message(self, chat_id: int, message_id: int) -> bool:
    """Telegram'dagi OTP xabarini o'chirish.

    OTP yuborilgandan OTP_EXPIRE_MINUTES + 30s o'tgach chaqiriladi — bot
    bilan suhbatdagi kod history'da qolmasligi uchun. Telegram deleteMessage
    API 48 soatlik chegaraga ega — bu vaqt ichida sig'adi.

    Xato bo'lsa retry'siz — Telegram qabul qilmasa (xabar allaqachon
    o'chirilgan, chat archived, va h.k.) qayta urinishning ma'nosi yo'q.
    """
    return delete_telegram_message(chat_id, message_id)
