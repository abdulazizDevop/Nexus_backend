"""Celery base task + cross-cutting tasklar.

`BaseTask` har task chaqirilganda:
  - `request_id` contextvar'iga Celery task ID ni yozadi
  - `task_name` va `task_retries` ni extra context'ga qo'shadi
  - Task yakunida context'ni tozalaydi

Shunday qilib task ichida chaqirilgan har qanday `logger.info(...)` avtomatik
`request_id=<celery-task-id>`, `task_name=<task.name>` maydonlari bilan JSON log
chiqaradi — Better Stack'da shu ID orqali bitta task run'ning barcha loglarini
topish mumkin.
"""

import logging
from io import StringIO

from celery import Task, shared_task
from django.core.management import call_command

from core.logging import (
    clear_log_context,
    request_id_ctx,
    set_log_context,
)

logger = logging.getLogger(__name__)


class BaseTask(Task):
    """Barcha tasklar uchun bazaviy klass — xato bo'lganda log yozadi."""

    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600  # max 10 daqiqa kutish
    max_retries = 3
    retry_jitter = True

    def before_start(self, task_id, _args, _kwargs):
        """Task ishga tushishidan oldin log context ni o'rnatish."""
        request_id_ctx.set(task_id)
        set_log_context(
            task_name=self.name,
            task_retries=self.request.retries if self.request else 0,
        )

    def after_return(self, _status, _retval, _task_id, _args, _kwargs, _einfo):
        """Task yakunida context ni tozalash (worker keyingi taskda ifloslanmaydi)."""
        clear_log_context()

    def on_failure(self, exc, _task_id, _args, _kwargs, einfo):
        logger.error(
            "task failed: %s",
            exc,
            exc_info=einfo,
            extra={"event": "task_failure"},
        )

    def on_retry(self, exc, _task_id, _args, _kwargs, _einfo):
        logger.warning(
            "task retry: %s",
            exc,
            extra={"event": "task_retry"},
        )

    def on_success(self, _retval, _task_id, _args, _kwargs):
        logger.info(
            "task completed",
            extra={"event": "task_success"},
        )


@shared_task(base=BaseTask, bind=True, name="core.translate_missing_catalogs")
def translate_missing_catalogs(self):
    """3 tilga to'lmagan katalog yozuvlarini Gemini orqali tarjima qilish.

    Idempotent — 3 til to'liq bo'lgan yozuvlarni skip qiladi. Force yo'q,
    chunki bu nightly cron, admin qo'l bilan to'g'rilashlarini buzmasligi
    uchun.

    Throttle 1.0s (Gemini rate limit'ni hisobga olib).
    """
    out = StringIO()
    try:
        call_command(
            "translate_existing",
            stdout=out,
            stderr=out,
            throttle=1.0,
        )
        result = out.getvalue()
        logger.info("Nightly i18n translation completed: %s", result[:500])
        return {"status": "ok", "output_preview": result[:500]}
    except Exception as exc:
        logger.exception("Nightly i18n translation failed")
        return {"status": "error", "error": str(exc)}
