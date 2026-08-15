import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def send_telegram_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    message_thread_id: int | None = None,
) -> bool:
    """Telegram bot orqali xabar yuborish (ixtiyoriy inline tugmalar bilan).

    `message_thread_id` — forum (topics yoqilgan) guruhda aniq mavzuga yuborish uchun.
    """
    result = send_telegram_message_with_id(
        chat_id, text, reply_markup, message_thread_id
    )
    return result is not None


def send_telegram_message_with_id(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    message_thread_id: int | None = None,
) -> int | None:
    """Telegram bot orqali xabar yuborish — message_id qaytaradi.

    Yuborilgan xabarni keyinroq o'chirish uchun message_id kerak (masalan,
    OTP kod chat history'da qolmasligi uchun).

    `reply_markup` — Telegram InlineKeyboardMarkup JSON dict (ixtiyoriy), masalan:
    `{"inline_keyboard": [[{"text": "✅ Bajardim", "callback_data": "dose:12:..."}]]}`.

    Returns: message_id (int) — muvaffaqiyatli, None — xato.
    """
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        if reply_markup:
            payload["reply_markup"] = reply_markup
        response = httpx.post(
            url,
            json=payload,
            timeout=10,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        if not data.get("ok"):
            return None
        return data.get("result", {}).get("message_id")
    except (httpx.RequestError, ValueError):
        return None


def send_account_deletion_notice(text: str) -> None:
    """Akkaunt o'chirish xabarini root admin + qo'shimcha chat_id larга yuboradi.

    Qabul qiluvchilar: `ROOT_ADMIN_PHONE` egasining telegram_chat_id'si +
    `ACCOUNT_DELETION_NOTIFY_CHAT_IDS` (settings). Best-effort — har biri alohida
    try/except, bittasi xato bersa qolganlari yuboriladi.
    """
    from django.contrib.auth import get_user_model

    chat_ids: list = []
    root_phone = getattr(settings, "ROOT_ADMIN_PHONE", "")
    if root_phone:
        User = get_user_model()
        root_admin = User.objects.filter(phone=root_phone).first()
        if root_admin and root_admin.telegram_chat_id:
            chat_ids.append(root_admin.telegram_chat_id)
    chat_ids.extend(getattr(settings, "ACCOUNT_DELETION_NOTIFY_CHAT_IDS", []))

    seen: set = set()
    for raw in chat_ids:
        try:
            cid = int(raw)
        except (ValueError, TypeError):
            continue
        if cid in seen:
            continue
        seen.add(cid)
        try:
            send_telegram_message(cid, text)
        except Exception as e:  # noqa: BLE001 — best-effort notify
            logger.warning("deletion notice send failed chat=%s err=%s", cid, e)


def delete_telegram_message(chat_id: int, message_id: int) -> bool:
    """Telegram'dan yuborilgan xabarni o'chirish.

    Telegram chegarasi: bot faqat o'zi yuborgan xabarlarni (bot'dagi shaxsiy
    suhbatda) 48 soat ichida o'chira oladi. OTP delete uchun yetarli.
    """
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/deleteMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=10,
        )
        return response.status_code == 200 and response.json().get("ok", False)
    except (httpx.RequestError, ValueError) as e:
        logger.warning(
            "delete_telegram_message failed chat=%s msg=%s err=%s",
            chat_id, message_id, e,
        )
        return False


def get_auth_deeplink(phone: str, role: str = "patient") -> str:
    """Unified auth deeplink — auth_<role>_<phone>.

    Bot DB tekshirib, mavjud user uchun login OTP, yangi user uchun ro'yxatga
    olish flow'ini boshlaydi. Frontend ikkalasini ham bilmaydi (xavfsizlik).
    """
    clean_phone = phone.lstrip("+")
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start=auth_{role}_{clean_phone}"


def send_otp_via_telegram(chat_id: int, code: str) -> bool:
    """OTP kodni Telegram orqali yuborish.

    OTP_EXPIRE_MINUTES + 30s'dan keyin chat'dan avtomatik o'chiriladi — bot
    xabaridagi kod history'da qolmasligi uchun (boshqa qurilmaga login
    qilingan eski chat'da OTP qolib ketishi xavfi kamayadi).
    """
    text = (
        f"🔐 <b>Mediik tasdiqlash kodi</b>\n\n"
        f"Sizning kodingiz: <code>{code}</code>\n\n"
        f"⏱ Kod {settings.OTP_EXPIRE_MINUTES} daqiqa ichida amal qiladi.\n"
        f"❗ Kodni hech kimga bermang!"
    )
    message_id = send_telegram_message_with_id(chat_id, text)
    if message_id is None:
        return False

    # Auto-delete OTP_EXPIRE_MINUTES + 30s dan keyin (kod amal qilmasligi
    # bilan birga chat'dan ham yo'qoladi). Celery task'sis bo'lsa silently skip.
    try:
        from app.auth.tasks import delete_otp_telegram_message

        delay = settings.OTP_EXPIRE_MINUTES * 60 + 30
        delete_otp_telegram_message.apply_async(
            args=[chat_id, message_id], countdown=delay
        )
    except Exception as e:
        # Celery yo'q yoki Redis o'chiq — OTP yuborildi, delete'siz ham OK.
        logger.warning("OTP auto-delete schedule failed: %s", e)

    return True
