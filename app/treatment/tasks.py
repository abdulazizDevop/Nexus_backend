import logging
from datetime import datetime
from datetime import timezone as dt_timezone

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from app.notifications.models import Notification
from app.notifications.utils import notify_by_key
from app.treatment.models import Treatment, TreatmentLog
from app.treatment.telegram_actions import dose_reminder_keyboard
from core.tasks import BaseTask
from services.telegram import send_telegram_message

logger = logging.getLogger(__name__)

# Eslatma oynasi (daqiqa): slot vaqti 0..N daqiqa oldin bo'lsa eslatma yuboriladi.
# Beat har daqiqa ishlagani uchun kichik oyna + per-slot cache dedup (bir slot bir
# marta) — aniq vaqtda yetkaziladi. Beat interval o'zgarsa shu qiymatni moslang.
REMINDER_WINDOW_MINUTES = 2

# Bir slot uchun "eslatma yuborildi" cache bayrog'i shuncha soat saqlanadi
# (kun davomida qayta yubormaslik uchun; kalit slot vaqtini o'z ichiga oladi).
REMINDER_DEDUP_TTL_SECONDS = 12 * 3600


@shared_task(base=BaseTask, name="treatment.send_reminder")
def send_treatment_reminder(user_id, treatment_id, slot_epoch=None):
    """Muolaja eslatmasini Telegram (inline '✅ Bajardim' tugma bilan) + Push orqali yuboradi.

    `slot_epoch` — slotning unix vaqti (per-slot rejali dori). Berilsa: status
    ko'rsatiladi + "Bajardim" tugmasi (callback o'sha slotni completed qiladi).
    Berilmasa (legacy) — oddiy matn, tugmasiz.
    """
    # Treatment navbatga qo'yilgandan keyin o'chirilgan bo'lishi mumkin —
    # bu holatda DoesNotExist'ni tinch ushlab qaytamiz.
    try:
        treatment = Treatment.objects.select_related("user").get(
            id=treatment_id, user_id=user_id
        )
    except Treatment.DoesNotExist:
        return {"status": "skipped", "reason": "treatment_deleted"}

    slot_dt = None
    if slot_epoch is not None:
        slot_dt = datetime.fromtimestamp(int(slot_epoch), tz=dt_timezone.utc)
        # Race: navbatda turganda bemor slotni allaqachon bajargan bo'lsa — eslatmaymiz.
        if TreatmentLog.objects.filter(
            treatment=treatment,
            scheduled_for=slot_dt,
            status=TreatmentLog.Status.COMPLETED,
        ).exists():
            return {"status": "skipped", "reason": "already_done"}

    type_display = treatment.get_type_display()
    if slot_dt is not None:
        time_str = timezone.localtime(slot_dt).strftime("%H:%M")
    else:
        time_str = treatment.time.strftime("%H:%M") if treatment.time else ""

    telegram_sent = False
    if treatment.user.telegram_chat_id:
        lines = [
            f"⏰ Eslatma: {treatment.title}",
            f"📋 {type_display}",
        ]
        if treatment.dosage:
            lines.append(f"💊 Dozasi: {treatment.dosage}")
        if time_str:
            lines.append(f"🕐 Vaqti: {time_str}")
        # Holat + tugma faqat per-slot (scheduled) eslatmalarda.
        reply_markup = None
        if slot_dt is not None:
            lines.append("")
            lines.append("⏳ Holat: bajarilmagan")
            reply_markup = dose_reminder_keyboard(treatment.id, slot_dt)

        send_telegram_message(
            treatment.user.telegram_chat_id, "\n".join(lines), reply_markup=reply_markup
        )
        telegram_sent = True

    body_parts = [type_display]
    if treatment.dosage:
        body_parts.append(treatment.dosage)
    if time_str:
        body_parts.append(time_str)

    push_data = {"treatment_id": str(treatment.id)}
    if slot_dt is not None:
        push_data["scheduled_for"] = slot_dt.isoformat()  # app ham shu slotni belgilaydi

    notification = notify_by_key(
        treatment.user,
        type=Notification.Type.TREATMENT_REMINDER,
        key="treatment_reminder",
        params={
            "title": treatment.title,
            "summary": " • ".join(body_parts),
        },
        data=push_data,
        app_scope="patient",
    )
    push_sent = notification is not None

    return {
        "status": "sent" if (telegram_sent or push_sent) else "skipped",
        "telegram": telegram_sent,
        "push": push_sent,
        "user_id": user_id,
        "treatment_id": treatment_id,
    }


@shared_task(base=BaseTask, name="treatment.check_daily_treatments")
def check_daily_treatments():
    """Har daqiqa muolaja SLOTLARINI tekshiradi va aniq vaqtda eslatma yuboradi (per-slot).

    Har dori vaqti (slot) mustaqil: o'sha slot uchun bir marta eslatma (cache dedup),
    slot allaqachon bajarilgan bo'lsa — yubormaydi. PRN (is_as_needed) — jadvalsiz, chetda.
    """
    now = timezone.localtime()
    today = now.date()
    now_minutes = now.hour * 60 + now.minute

    treatments = Treatment.objects.filter(
        status=Treatment.Status.ACTIVE,
    ).select_related("user")

    # Bugungi loglar — per-slot bajarilgan (scheduled_for) + legacy (null) belgilangan.
    completed_slots = set()         # (treatment_id, scheduled_for) — bajarilgan slotlar
    marked_legacy_treatments = set()  # treatment_id — null-scheduled_for log (eski kun-darajasi)
    for tid, sched, st in TreatmentLog.objects.filter(date=today).values_list(
        "treatment_id", "scheduled_for", "status"
    ):
        if sched is not None:
            if st == TreatmentLog.Status.COMPLETED:
                completed_slots.add((tid, sched))
        else:
            marked_legacy_treatments.add(tid)

    sent = 0
    for treatment in treatments:
        if treatment.is_as_needed:
            continue  # PRN — jadvalsiz, eslatma yo'q
        if not treatment.is_scheduled_today():
            continue
        if treatment.end_date and treatment.end_date < today:
            treatment.status = Treatment.Status.COMPLETED
            treatment.save(update_fields=["status"])
            continue
        # Legacy: bugun kun-darajasida belgilangan bo'lsa — slot eslatmalari yubormaymiz.
        if treatment.id in marked_legacy_treatments:
            continue

        for t in treatment.get_scheduled_times():
            slot_minutes = t.hour * 60 + t.minute
            elapsed = now_minutes - slot_minutes
            # Slot vaqti 0..N daqiqa oldin bo'lsa eslatma vaqti keldi.
            if not (0 <= elapsed <= REMINDER_WINDOW_MINUTES):
                continue
            slot_dt = timezone.make_aware(datetime.combine(today, t))
            if (treatment.id, slot_dt) in completed_slots:
                continue  # slot allaqachon bajarilgan
            # Bir slot uchun bir marta eslatma (cache dedup — beat har daqiqa ishlaydi).
            cache_key = f"trx_remind:{treatment.id}:{int(slot_dt.timestamp())}"
            if not cache.add(cache_key, 1, timeout=REMINDER_DEDUP_TTL_SECONDS):
                continue
            send_treatment_reminder.delay(
                treatment.user_id,
                treatment.id,
                int(slot_dt.timestamp()),
            )
            sent += 1

    return {"checked_at": str(now), "reminders_sent": sent}
