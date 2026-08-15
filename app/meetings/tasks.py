import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.utils import timezone

from app.feedbacks.models import Review
from app.meetings.models import Appointment
from app.notifications.models import Notification
from app.notifications.utils import notify_by_key
from core.tasks import BaseTask
from services.livekit import create_room

logger = logging.getLogger(__name__)

AUTO_COMPLETE_GRACE_HOURS = 2
CONSULTATION_PAYMENT_TTL_MIN = 30  # to'lanmagan konsultatsiya shu daqiqada expired


@shared_task(base=BaseTask, bind=True, name="meetings.create_livekit_room")
def create_livekit_room(self, room_name: str, appointment_id: int):
    """LiveKit serverda room yaratadi. Xato bo'lsa BaseTask 3 marta retry qiladi."""
    create_room(room_name)
    logger.info(
        "LiveKit room yaratildi: %s (appointment #%s)", room_name, appointment_id
    )


@shared_task(base=BaseTask, bind=True, name="meetings.auto_complete_appointments")
def auto_complete_appointments(self):
    """Approved appointmentlarni avtomatik COMPLETED ga o'tkazadi.

    Doctor "complete" bosishni unutsa, qabul tugaganidan keyin 2 soat o'tgach
    sistema o'zi yakunlaydi — patient review yozolishi uchun.

    Har 30 daqiqada ishga tushadi (CELERY_BEAT_SCHEDULE'dan).
    """
    now = timezone.now()
    today = now.date()
    tz = timezone.get_current_timezone()

    # Avval keng filtr: bugun yoki kechagidan oldin tugagan approved appointmentlar
    candidates = Appointment.objects.filter(
        status=Appointment.Status.APPROVED,
        date__lte=today,
    )

    completed_ids = []
    for appt in candidates.iterator():
        end_dt = datetime.combine(appt.date, appt.end_time, tzinfo=tz)
        if end_dt + timedelta(hours=AUTO_COMPLETE_GRACE_HOURS) <= now:
            completed_ids.append(appt.id)

    if not completed_ids:
        return 0

    # Faqat haqiqatan APPROVED bo'lib turgan id'larni oldindan aniqlaymiz —
    # konkurent cancel/complete bo'lgan candidate'lar update'dan o'tmaydi,
    # shu sababli ularga keraksiz review-request task navbatga qo'yilmasin.
    to_update_ids = list(
        Appointment.objects.filter(
            id__in=completed_ids,
            status=Appointment.Status.APPROVED,  # race-safe: faqat approved'lar
        ).values_list("id", flat=True)
    )
    if not to_update_ids:
        return 0

    updated = Appointment.objects.filter(
        id__in=to_update_ids,
        status=Appointment.Status.APPROVED,
    ).update(status=Appointment.Status.COMPLETED, updated_at=now)

    logger.info("Auto-completed %d ta appointment: %s", updated, to_update_ids)

    for appt_id in to_update_ids:
        send_review_request_notification.delay(appt_id)

    return updated


@shared_task(base=BaseTask, bind=True, name="meetings.auto_complete_consultations")
def auto_complete_consultations(self):
    """Confirmed konsultatsiyalarni vaqti o'tgach avtomatik COMPLETED ga o'tkazadi.

    Tugash vaqtidan CONSULTATION_AUTO_COMPLETE_GRACE_MIN daqiqa o'tgach (call-oyna
    end + CALL_GRACE_MIN allaqachon yopiq) CONFIRMED -> COMPLETED. Aks holda
    konsultatsiya abadiy `confirmed` qolardi (Appointment'dan alohida model — u
    auto_complete_appointments bilan yakunlanadi, Consultation qamralmagan edi).
    Har 30 daqiqada (CELERY_BEAT_SCHEDULE).
    """
    from app.meetings.models import (
        CONSULTATION_AUTO_COMPLETE_GRACE_MIN,
        Consultation,
    )

    now = timezone.now()
    tz = timezone.get_current_timezone()
    grace = timedelta(minutes=CONSULTATION_AUTO_COMPLETE_GRACE_MIN)
    completed_ids = [
        cid
        for cid, cdate, cend in Consultation.objects.filter(
            status=Consultation.Status.CONFIRMED,
            date__lte=timezone.localdate(),
        ).values_list("id", "date", "end_time")
        if datetime.combine(cdate, cend, tzinfo=tz) + grace <= now
    ]
    if not completed_ids:
        return 0
    # Race-safe: faqat hali CONFIRMED bo'lganlar (parallel cancel/webhook bilan).
    updated = Consultation.objects.filter(
        id__in=completed_ids,
        status=Consultation.Status.CONFIRMED,
    ).update(status=Consultation.Status.COMPLETED, updated_at=now)
    if updated:
        logger.info("Auto-completed %d ta konsultatsiya: %s", updated, completed_ids)
    return updated


@shared_task(base=BaseTask, bind=True, name="meetings.send_review_request_notification")
def send_review_request_notification(self, appointment_id: int):
    """Patientga review yozish so'rovi (push + in-app notification)."""
    try:
        appt = Appointment.objects.select_related("patient", "doctor__user").get(
            id=appointment_id
        )
    except Appointment.DoesNotExist:
        return

    if appt.status != Appointment.Status.COMPLETED:
        return

    # Idempotent — review allaqachon yozilgan bo'lsa, qaytarmaymiz
    if Review.objects.filter(appointment_id=appointment_id).exists():
        return

    notify_by_key(
        user=appt.patient,
        type=Notification.Type.REVIEW_REMINDER,
        key="review_request",
        params={"doctor_name": appt.doctor.user.full_name or "shifokor"},
        data={"appointment_id": appointment_id, "doctor_id": appt.doctor_id},
        app_scope="patient",
    )


@shared_task(base=BaseTask, bind=True, name="meetings.expire_unpaid_consultations")
def expire_unpaid_consultations(self):
    """To'lanmagan konsultatsiyalar (pending_payment, TTL o'tgan) → expired + slot free.

    Hold = min(booking + CONSULTATION_PAYMENT_TTL_MIN, slot_start + grace) — yaqin
    slotda grace o'tsa TTL kutilmaydi. Slot bo'shatiladi (boshqa bemor band qila
    oladi). Har-slot atomic + select_for_update (webhook confirm bilan poyga
    xavfsiz — confirm PENDING_PAYMENT'dan chiqarsa, bu skip qiladi).
    """
    from django.db import transaction

    from app.doctors.models import Slot
    from app.meetings.models import CONSULTATION_SLOT_GRACE_MIN, Consultation

    # Hold = min(booking + TTL, slot_start + grace). Yaqin slot uchun TTL kutmaymiz —
    # aks holda to'lanmagan booking slot boshlanib grace ham o'tgach ham 30 daqiqagacha
    # bloklab turadi (boshqa bemor band qila olmaydi). Ikkovidan qaysi avval — o'sha.
    now = timezone.now()
    ttl = timedelta(minutes=CONSULTATION_PAYMENT_TTL_MIN)
    grace = timedelta(minutes=CONSULTATION_SLOT_GRACE_MIN)
    tz = timezone.get_current_timezone()
    stale_ids = [
        cid
        for cid, created_at, cdate, ctime in Consultation.objects.filter(
            status=Consultation.Status.PENDING_PAYMENT,
        ).values_list("id", "created_at", "date", "start_time")
        if now
        > min(
            created_at + ttl,
            timezone.make_aware(datetime.combine(cdate, ctime), tz) + grace,
        )
    ]
    count = 0
    for cid in stale_ids:
        with transaction.atomic():
            c = (
                Consultation.objects.select_for_update()
                .filter(id=cid, status=Consultation.Status.PENDING_PAYMENT)
                .first()
            )
            if not c:
                continue  # confirm yoki boshqa jarayon o'zgartirdi
            c.status = Consultation.Status.EXPIRED
            c.save(update_fields=["status", "updated_at"])
            slot = Slot.objects.select_for_update().filter(consultation=c).first()
            if slot:
                slot.status = Slot.Status.FREE
                slot.consultation = None
                slot.save(update_fields=["status", "consultation", "updated_at"])
            count += 1
    if count:
        logger.info(
            "expire_unpaid_consultations: %s ta konsultatsiya expired + slot bo'shatildi",
            count,
        )
    return count
