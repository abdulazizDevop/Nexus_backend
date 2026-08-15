"""Tracking AI Celery tasklari (pattern: app/health_ai/tasks.py).

Har kuni 06:30 (health_ai'dan 30 daqiqa keyin — stagger) barcha faol
bemorlar bo'yicha kunlik AI kuzatuv hisoboti yaratiladi. KRITIK holatda
bemor + ACCEPTED shifokorlar + ACCEPTED oila a'zolariga push boradi.
"""

import logging

from celery import shared_task

from core.tasks import BaseTask

logger = logging.getLogger("mediik.tracking_ai")


@shared_task(base=BaseTask, name="tracking_ai.generate_daily_tracking")
def generate_daily_tracking():
    """Fan-out: kecha faollik ko'rsatgan har bir bemorga alohida subtask."""
    from datetime import timedelta

    from django.utils import timezone

    from app.health_packages.models import DailySituationCheckup, HealthIndicator
    from app.treatment.models import TreatmentLog

    period_date = timezone.localdate() - timedelta(days=1)

    user_ids = set(
        HealthIndicator.objects.filter(date=period_date).values_list("user_id", flat=True)
    )
    user_ids |= set(
        TreatmentLog.objects.filter(date=period_date).values_list("user_id", flat=True)
    )
    user_ids |= set(
        DailySituationCheckup.objects.filter(date=period_date).values_list(
            "user_id", flat=True
        )
    )

    queued = 0
    for uid in user_ids:
        try:
            generate_one_tracking.delay(
                patient_id=uid, period_date=period_date.isoformat()
            )
            queued += 1
        except Exception:
            logger.exception("Tracking subtask queue xatosi user=%s", uid)
    return {"queued": queued, "period_date": period_date.isoformat()}


@shared_task(base=BaseTask, bind=True, name="tracking_ai.generate_one_tracking")
def generate_one_tracking(self, patient_id, period_date, force=False, language=None):
    """Bitta bemor uchun kunlik hisobot: idempotent + activity filter + upsert."""
    from datetime import date as date_cls

    from django.contrib.auth import get_user_model

    from services.gemini import generate_text

    from . import prompts, services
    from .models import AITrackingReport

    User = get_user_model()
    day = date_cls.fromisoformat(period_date)
    user = User.objects.filter(id=patient_id).first()
    if not user:
        return {"error": "user_not_found"}

    profile = getattr(user, "patient_profile", None)
    if profile is None:
        return {"skipped": "no_patient_profile"}

    # 1) Idempotent — shu kun uchun hisobot bo'lsa qayta yaratmaymiz (force'siz).
    if not force and AITrackingReport.objects.filter(
        patient_profile=profile, period_start=day
    ).exists():
        return {"skipped": "exists"}

    # 2) Activity filter — ma'lumot yo'q bo'lsa Gemini chaqirmaymiz.
    if not force and not services.has_activity(user, day):
        return {"skipped": "no_activity"}

    # 3) Kontekst + data + prompt (bemor tili).
    lang = language or getattr(getattr(user, "settings", None), "language", None) or "uz"
    context = services.build_patient_context(user)
    data = services.build_tracking_data(user, day)
    adherence_percent, _ = services.compute_adherence(user, day)
    system_prompt = prompts.build_tracking_system_prompt(lang, context)

    # 4) Gemini structured JSON (past temperature — barqaror natija).
    result = generate_text(
        prompt=(
            "Quyidagi kunlik ma'lumotlar asosida bemor uchun kuzatuv hisobotini tuz:\n\n"
            + data
        ),
        system_instruction=system_prompt,
        response_schema=prompts.TRACKING_REPORT_SCHEMA,
        temperature=0.3,
    )
    if "error" in result:
        return {"error": result["error"]}

    parsed = services.parse_tracking_response(result.get("text") or "")
    if not parsed:
        return {"error": "parse_failed"}

    # 5) Upsert — unique (patient_profile, period_start).
    report, _created = AITrackingReport.objects.update_or_create(
        patient_profile=profile,
        period_start=day,
        defaults={
            "patient": user,
            "period_end": day,
            "summary": parsed.get("summary", ""),
            "detected_changes": parsed.get("detected_changes", []),
            "recommendations": parsed.get("recommendations", []),
            "adherence_percent": adherence_percent,
            "severity": parsed.get("severity", AITrackingReport.Severity.NORMAL),
            "tokens_input": result.get("tokens_input", 0),
            "tokens_output": result.get("tokens_output", 0),
        },
    )

    # 6) KRITIK bo'lsa — bemor, shifokorlar va oila a'zolariga push.
    if report.severity == AITrackingReport.Severity.CRITICAL:
        _send_critical_alerts(report)

    return {"report_id": report.id, "severity": report.severity}


def _send_critical_alerts(report):
    """KRITIK hisobot: bemor (patient app), shifokorlar (doctor app), oila (patient app)."""
    from django.contrib.auth import get_user_model

    from app.notifications.models import Notification
    from app.notifications.utils import notify

    User = get_user_model()
    body = (report.summary or "")[:200]
    data = {"kind": "tracking_alert", "report_id": report.id, "patient_id": report.patient_id}

    def _safe_notify(target_user, title, app_scope):
        try:
            notify(
                target_user,
                type=Notification.Type.TRACKING_ALERT,
                title=title,
                body=body,
                data=data,
                app_scope=app_scope,
            )
        except Exception:
            logger.exception(
                "Tracking alert push xatosi report=%s user=%s", report.id, target_user.id
            )

    # Bemorning o'zi
    _safe_notify(report.patient, "AI kuzatuv: e'tibor talab qilinadi", "patient")

    # ACCEPTED shifokorlar
    try:
        from app.doctors.models import DoctorPatient

        doctor_users = User.objects.filter(
            doctor_profile__doctor_patients__patient_id=report.patient_id,
            doctor_profile__doctor_patients__status=DoctorPatient.Status.ACCEPTED,
        ).distinct()
        for du in doctor_users:
            _safe_notify(du, f"AI kuzatuv: {report.patient.full_name}", "doctor")
    except Exception:
        logger.exception("Tracking alert doctor fan-out xatosi report=%s", report.id)

    # ACCEPTED oila a'zolari
    try:
        from app.family.models import family_member_user_ids

        for mu in User.objects.filter(id__in=family_member_user_ids(report.patient_id)):
            _safe_notify(mu, f"AI kuzatuv: {report.patient.full_name}", "patient")
    except ImportError:
        pass
    except Exception:
        logger.exception("Tracking alert family fan-out xatosi report=%s", report.id)
