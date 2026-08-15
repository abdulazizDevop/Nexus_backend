"""Structured JSON logging for Better Stack / any log aggregator.

Ikki narsani beradi:

1. `JsonFormatter` — har logni bir qatorli JSON qilib chiqaradi, Better Stack
   uni avtomatik parse qiladi (level, path, user_id va h.k. bo'yicha filter).
2. Contextvar'lar (`request_id_ctx`, `user_id_ctx`, `user_role_ctx`) —
   request davomida chaqirilgan har qanday logger avtomatik shu kontekstni
   qo'shib yuboradi. Middleware ularni set qiladi.

Formatter stdlib asosida yozilgan — hech qanday yangi dependency kerak emas.

Ishlatish:
    logger = logging.getLogger("mediik.payments")
    logger.info("payment completed", extra={"payment_id": 42, "amount": 99000})

JSON chiqishi:
    {"timestamp": "...", "level": "INFO", "logger": "mediik.payments",
     "message": "payment completed", "request_id": "...", "user_id": 7,
     "payment_id": 42, "amount": 99000, ...}
"""

from __future__ import annotations

import json
import logging
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Request-scoped context
# ---------------------------------------------------------------------------
# Middleware shularni set qiladi. Celery/bot'da ham qo'lda set qilsa bo'ladi.

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[int | None] = ContextVar("user_id", default=None)
user_role_ctx: ContextVar[str | None] = ContextVar("user_role", default=None)

# Ixtiyoriy qo'shimcha maydonlar — har qanday key/value saqlash uchun.
# Masalan: task_name, telegram_user_id, celery_queue, chat_id va h.k.
# set_log_context(task_name="send_otp") → har log ga task_name qo'shiladi.
_extra_ctx: ContextVar[dict[str, Any] | None] = ContextVar("extra", default=None)


# LogRecord ning standart maydonlari — ularni JSON ga qaytarmaymiz
# (chunki o'zimiz ularni alohida format qilamiz).
_RESERVED_RECORD_FIELDS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Bir qatorli JSON formatter.

    Maydonlar:
      - timestamp   — ISO 8601, UTC
      - level       — INFO/WARNING/ERROR/...
      - logger      — logger nomi
      - message     — formatlangan xabar
      - service     — qaysi konteyner (web/bot/celery/beat/flower)
      - environment — development/production
      - source      — module.funcName:lineno (debug uchun)
      - request_id, user_id, user_role — contextvar'lardan (bor bo'lsa)
      - exception   — {type, message, traceback} (exc_info bo'lsa)
      - extra={}    — logger chaqirilgan joydan kelgan qo'shimcha maydonlar
    """

    def __init__(self, service: str = "web", environment: str = "development") -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
            "source": f"{record.module}.{record.funcName}:{record.lineno}",
        }

        # Request-scoped context
        request_id = request_id_ctx.get()
        if request_id is not None:
            payload["request_id"] = request_id
        user_id = user_id_ctx.get()
        if user_id is not None:
            payload["user_id"] = user_id
        user_role = user_role_ctx.get()
        if user_role is not None:
            payload["user_role"] = user_role

        # Ixtiyoriy context field'lar (set_log_context orqali qo'yilgan)
        extra = _extra_ctx.get()
        if extra:
            for key, value in extra.items():
                if key not in payload:
                    payload[key] = value

        # Exception
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                ),
            }

        # Extra maydonlar (logger.info("msg", extra={...}) dan kelgan).
        # Serialize qilib bo'lmaydigan qiymatlar `default=repr` orqali tushib
        # qoladi — har field uchun alohida json.dumps test qilish shart emas.
        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_FIELDS or key.startswith("_"):
                continue
            if key in payload:
                continue
            payload[key] = value

        return json.dumps(payload, ensure_ascii=False, default=repr)


# ---------------------------------------------------------------------------
# Helpers (Celery task / Telegram bot ichida context ni qo'lda set qilish uchun)
# ---------------------------------------------------------------------------

def set_log_context(
    *,
    request_id: str | None = None,
    user_id: int | None = None,
    user_role: str | None = None,
    **extra: Any,
) -> None:
    """Contextvar'larni set qilish. Celery task boshida yoki bot handler'da.

    Standart maydonlar (typed): request_id, user_id, user_role.
    Ixtiyoriy maydonlar (kwargs): istalgan key/value — _extra_ctx ga merge qilinadi.

    Ishlatish:
        # Oddiy
        set_log_context(user_id=42, user_role="doctor")

        # Ixtiyoriy maydonlar bilan
        set_log_context(task_name="send_otp", telegram_user_id=123456)

        # Faqat ixtiyoriy
        set_log_context(chat_id=999, handler="start_deeplink")
    """
    if request_id is not None:
        request_id_ctx.set(request_id)
    if user_id is not None:
        user_id_ctx.set(user_id)
    if user_role is not None:
        user_role_ctx.set(user_role)

    if extra:
        current = _extra_ctx.get() or {}
        _extra_ctx.set({**current, **extra})


def clear_log_context() -> None:
    """Contextvar'larni tozalash (task/request yakunida)."""
    request_id_ctx.set(None)
    user_id_ctx.set(None)
    user_role_ctx.set(None)
    _extra_ctx.set(None)
