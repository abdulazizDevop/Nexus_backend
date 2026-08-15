from celery import shared_task

from core.tasks import BaseTask


@shared_task(base=BaseTask, name="medical.check_analysis_deadlines")
def check_analysis_deadlines():
    """Har soatda — deadline'ga 24 soat qolgan analizlar uchun bemorga eslatma.

    Idempotent: `reminder_sent_at` to'ldirilgan bo'lsa qaytadan yubormaydi.
    """
    from datetime import timedelta

    from django.utils import timezone

    from app.medical.models import Analysis

    now = timezone.now()
    window_start = now
    window_end = now + timedelta(hours=24)

    pending = (
        Analysis.objects.select_related("patient", "type")
        .filter(
            status=Analysis.Status.PRESCRIBED,
            deadline_at__gte=window_start,
            deadline_at__lte=window_end,
            reminder_sent_at__isnull=True,
        )
    )

    sent = 0
    for analysis in pending:
        try:
            from app.notifications.models import Notification
            from app.notifications.utils import notify_by_key

            hours_left = max(
                1, int((analysis.deadline_at - now).total_seconds() // 3600)
            )
            notify_by_key(
                analysis.patient,
                type=Notification.Type.SYSTEM,
                key="analysis_deadline_reminder",
                params={
                    "type_name": analysis.type_name_for(analysis.patient),
                    "hours": hours_left,
                },
                data={
                    "kind": "analysis_deadline_reminder",
                    "analysis_id": str(analysis.id),
                },
                app_scope="patient",
            )
            analysis.reminder_sent_at = now
            analysis.save(update_fields=["reminder_sent_at", "updated_at"])
            sent += 1
        except Exception:
            continue

    return {"sent": sent, "checked": pending.count()}


@shared_task(base=BaseTask, name="medical.expire_overdue_analyses")
def expire_overdue_analyses():
    """Deadline o'tib ketgan va submit qilinmagan analizlar uchun bemorga
    bir martalik 'overdue' eslatma yuboradi.

    DIQQAT: bu task analiz STATUSINI o'zgartirmaydi — analiz PRESCRIBED holatda
    qoladi (UI 'overdue' deb ko'rsatadi). Faqat push xabar yuboradi va
    `reminder_sent_at` orqali idempotent.
    """
    from django.utils import timezone

    from app.medical.models import Analysis

    now = timezone.now()
    overdue = Analysis.objects.filter(
        status=Analysis.Status.PRESCRIBED,
        deadline_at__lt=now,
        reminder_sent_at__isnull=True,
    )

    sent = 0
    for analysis in overdue:
        try:
            from app.notifications.models import Notification
            from app.notifications.utils import notify_by_key

            notify_by_key(
                analysis.patient,
                type=Notification.Type.SYSTEM,
                key="analysis_overdue",
                params={"type_name": analysis.type_name_for(analysis.patient)},
                data={
                    "kind": "analysis_overdue",
                    "analysis_id": str(analysis.id),
                },
                app_scope="patient",
            )
            analysis.reminder_sent_at = now
            analysis.save(update_fields=["reminder_sent_at", "updated_at"])
            sent += 1
        except Exception:
            continue

    return {"sent": sent}
