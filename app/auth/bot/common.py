"""
Telegram bot (aiogram 3) — Mediik unified OTP authentication.

Unified flow:
1. User clicks deeplink: t.me/mediikuzbot?start=auth_<role>_<phone>
2. Bot DB tekshiradi:
   - Mavjud user → kontakt verify → login OTP
   - Yangi user → ism so'raydi → kontakt verify → register OTP
3. User ilovaga qaytib OTP'ni POST /auth/verify/ ga kiritadi → JWT

Frontend faqat /auth/ va /auth/verify/ endpointlarini biladi — register/login
farqi bot tomonida hal qilinadi (user enumeration himoyasi).

Run: python manage.py run_bot
"""

import asyncio
import html
import logging
import time

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    TelegramObject,
    Update,
)
from asgiref.sync import sync_to_async
from django.conf import settings

from django.contrib.auth import get_user_model

from app.auth.models import OTPCode
from app.auth.serializers import normalize_phone
from app.auth.tasks import delete_otp_telegram_message
from core.logging import clear_log_context, request_id_ctx, set_log_context


User = get_user_model()


router = Router()


bot_logger = logging.getLogger("mediik.bot")


schedule_logger = logging.getLogger("mediik.bot.schedule")


class LogContextMiddleware(BaseMiddleware):
    """Aiogram outer middleware — har update uchun log context o'rnatadi.

    Har Telegram update ga:
      - request_id = update_id (string)
      - telegram_user_id, telegram_username, chat_id (bo'lsa)
      - update_type (message / callback_query / ...)

    Update yakunida context tozalanadi + access log yoziladi (handler_duration_ms).
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        update_id = None
        telegram_user_id = None
        telegram_username = None
        chat_id = None
        update_type = type(event).__name__

        if isinstance(event, Update):
            update_id = event.update_id
            inner = (
                event.message
                or event.callback_query
                or event.edited_message
                or event.inline_query
            )
            if inner is not None:
                update_type = type(inner).__name__
                from_user = getattr(inner, "from_user", None)
                if from_user is not None:
                    telegram_user_id = from_user.id
                    telegram_username = from_user.username
                chat = getattr(inner, "chat", None) or getattr(
                    getattr(inner, "message", None), "chat", None
                )
                if chat is not None:
                    chat_id = chat.id

        request_id_ctx.set(str(update_id) if update_id else "bot-no-id")
        set_log_context(
            update_type=update_type,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            chat_id=chat_id,
        )

        start = time.perf_counter()
        try:
            return await handler(event, data)
        except Exception:
            bot_logger.exception(
                "bot handler failed",
                extra={"duration_ms": int((time.perf_counter() - start) * 1000)},
            )
            raise
        finally:
            bot_logger.info(
                "bot update handled",
                extra={
                    "duration_ms": int((time.perf_counter() - start) * 1000),
                },
            )
            clear_log_context()


class AuthStates(StatesGroup):
    """Unified auth FSM.

    Mavjud user — kontakt verify → login OTP.
    Yangi patient — ism → kontakt verify → register OTP.
    Yangi doctor  — ism → referral code → kontakt verify → register OTP.
    """

    waiting_login_contact = State()
    waiting_register_name = State()
    waiting_register_sex = State()
    waiting_register_referral = State()
    waiting_register_contact = State()


async def _get_admin_contact_text() -> str:
    """Admin kontakt ma'lumotlarini SystemSetting'dan oladi."""
    try:
        from app.payments.models import SystemSetting

        text = await sync_to_async(SystemSetting.get)(
            "support_contact_info",
            "📞 Qo'llab-quvvatlash: @mediik_support",
        )
        return str(text)
    except Exception:
        return "📞 Qo'llab-quvvatlash: @mediik_support"


@sync_to_async
def _user_exists_by_phone(phone: str) -> bool:
    """Telefon raqam DB da User sifatida ro'yxatdan o'tganmi."""
    return User.objects.filter(phone=phone).exists()


@sync_to_async
def _get_user_telegram_chat_id(phone: str) -> int | None:
    """User'ning bog'langan telegram_chat_id'sini qaytaradi (bo'lmasa None)."""
    user = User.objects.filter(phone=phone).only("telegram_chat_id").first()
    return user.telegram_chat_id if user and user.telegram_chat_id else None


@sync_to_async
def _is_valid_doctor_referral(code: str) -> bool:
    """Bot uchun async wrapper — sync helper view'da."""
    from app.auth.views import _is_valid_doctor_referral as sync_check

    return sync_check(code)


async def _schedule_otp_message_delete(chat_id: int, message_id: int) -> None:
    """OTP xabarini OTP_EXPIRE_MINUTES + 30s'dan keyin avtomatik o'chirish.

    Bot xabarida kod chat history'da qolmasligi uchun. Agar Celery yo'q yoki
    Redis o'chiq bo'lsa silently skip — OTP yuborilgan bo'lsa ham yetarli.
    """
    delay = settings.OTP_EXPIRE_MINUTES * 60 + 30
    try:
        await sync_to_async(delete_otp_telegram_message.apply_async)(
            args=[chat_id, message_id], countdown=delay
        )
    except Exception as e:
        schedule_logger.warning("Bot OTP auto-delete schedule failed: %s", e)


async def _send_otp_message(
    message: Message,
    state: FSMContext,
    chat_id: int,
    otp,
    header: str,
    code_label: str = "Sizning kodingiz",
) -> None:
    """OTP kodni chatga yuboradi, auto-delete rejalashtiradi, state'ni tozalaydi.

    4 handler'da takrorlangan 'answer + schedule_delete + state.clear' patternini
    bitta joyga yig'adi. `header` birinchi qator, `code_label` kod qatori prefiksi.
    """
    sent = await message.answer(
        f"{header}\n\n"
        f"🔐 {code_label}: <code>{otp.code}</code>\n\n"
        f"⏱ Kod {settings.OTP_EXPIRE_MINUTES} daqiqa ichida amal qiladi.\n"
        "📲 Ilovaga qaytib kodni kiriting.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _schedule_otp_message_delete(chat_id, sent.message_id)
    await state.clear()


def _contact_keyboard() -> ReplyKeyboardMarkup:
    """«Kontaktni ulashish» tugmali keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Kontaktni ulashish", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _validate_contact(
    message: Message, state: FSMContext
) -> tuple[str, str, int] | None:
    """Kontakt valid'ligini tekshirib (deeplink_phone, role, chat_id) qaytaradi.

    Mos kelmasa foydalanuvchiga xabar yuborib state'ni tozalaydi va None
    qaytaradi. Asynchron flow uchun yagona helper.
    """
    contact = message.contact

    if contact is None or contact.user_id != message.from_user.id:
        await message.answer(
            "❌ Faqat o'zingizning kontaktingizni ulashing.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return None

    data = await state.get_data()
    deeplink_phone = normalize_phone(data.get("phone", ""))
    contact_phone = normalize_phone(contact.phone_number or "")
    role = data.get("role", "patient")
    chat_id = data.get("chat_id") or message.chat.id

    if deeplink_phone != contact_phone:
        admin_info = await _get_admin_contact_text()
        await message.answer(
            "❌ <b>Telefon raqamlar mos kelmadi!</b>\n\n"
            f"📱 Ilovada kiritilgan: <code>{deeplink_phone}</code>\n"
            f"📲 Telegram raqamingiz: <code>{contact_phone}</code>\n\n"
            "Sizning Telegram boshqa raqamga ochilgan.\n\n"
            "💡 <b>Nima qilish kerak:</b>\n"
            "1️⃣ Ilovada Telegram raqamingizni kiriting va qaytadan urinib ko'ring\n"
            "2️⃣ Yoki adminlar bilan bog'laning:\n\n"
            f"{admin_info}",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return None

    return deeplink_phone, role, chat_id


def _sex_keyboard() -> InlineKeyboardMarkup:
    """Jins tanlash uchun 2 ta tugmali inline klaviatura."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👨 Erkak", callback_data="sex:male"),
                InlineKeyboardButton(text="👩 Ayol", callback_data="sex:female"),
            ]
        ]
    )


def _referral_skip_keyboard() -> InlineKeyboardMarkup:
    """Referral code'siz davom etish uchun skip tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="ref:skip")]
        ]
    )
