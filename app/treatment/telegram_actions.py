"""Telegram dori eslatmasi — inline "✅ Bajardim" tugma + callback bilan slotni belgilash.

Ikki tomon:
  - Yuborish (Celery, sync, httpx): `dose_reminder_keyboard()` → reply_markup dict.
  - Callback (bot process, aiogram): `mark_dose_from_telegram()` — tugma bosilganda
    slotni completed qiladi (sync — bot tomonda `sync_to_async` bilan chaqiriladi).

callback_data formati: "dose:{treatment_id}:{epoch}" — epoch = slot instantining
unix vaqti (ISO'dagi ':' delimiter'ni buzmasligi uchun epoch ishlatiladi; Telegram
callback_data 64 bayt chegarasiga ham mos).
"""

from datetime import datetime, timezone as _dt_timezone

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Treatment, TreatmentLog

User = get_user_model()

DOSE_CALLBACK_PREFIX = "dose"


def dose_callback_data(treatment_id: int, slot_dt: datetime) -> str:
    """"dose:{treatment_id}:{epoch}" — inline tugma callback_data'si."""
    return f"{DOSE_CALLBACK_PREFIX}:{treatment_id}:{int(slot_dt.timestamp())}"


def dose_reminder_keyboard(treatment_id: int, slot_dt: datetime) -> dict:
    """'✅ Bajardim' tugmali Telegram inline keyboard (reply_markup dict)."""
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Bajardim",
                    "callback_data": dose_callback_data(treatment_id, slot_dt),
                }
            ]
        ]
    }


def mark_dose_from_telegram(telegram_chat_id: int, treatment_id: int, epoch: int) -> str:
    """Telegram '✅ Bajardim' bosilganda slotni COMPLETED qiladi (sync).

    Bot tomonida `sync_to_async(mark_dose_from_telegram)(...)` bilan chaqiriladi.
    Returns: 'ok' | 'already' | 'no_user' | 'no_treatment'.
    """
    user = User.objects.filter(telegram_chat_id=telegram_chat_id).first()
    if not user:
        return "no_user"
    treatment = Treatment.objects.filter(id=treatment_id, user=user).first()
    if not treatment:
        return "no_treatment"

    slot_dt = datetime.fromtimestamp(epoch, tz=_dt_timezone.utc)
    existing = TreatmentLog.objects.filter(
        treatment=treatment, scheduled_for=slot_dt
    ).first()
    if existing and existing.status == TreatmentLog.Status.COMPLETED:
        return "already"

    # Per-slot idempotent (treatment, scheduled_for unique). Mavjud bo'lsa yangilaydi.
    TreatmentLog.objects.update_or_create(
        treatment=treatment,
        scheduled_for=slot_dt,
        defaults={
            "date": timezone.localtime(slot_dt).date(),
            "status": TreatmentLog.Status.COMPLETED,
            "completed_at": timezone.now(),
        },
    )
    return "ok"
