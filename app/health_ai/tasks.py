"""Health AI Celery tasklari — kunlik (06:00) AI insight report generatsiyasi.

Oqim: generate_daily_reports (DoctorPatient ACCEPTED loop, fan-out) →
generate_one_report (activity-filter + idempotent + multi-source pipeline +
Gemini + AIHealthReport upsert + critical bo'lsa doctorga push).
"""

import logging
from datetime import date as date_cls
from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from app.diet_ai.models import DietEntry
from app.doctors.models import DoctorPatient, DoctorProfile
from app.health_packages.models import HealthIndicator
from app.treatment.models import TreatmentLog
from core.tasks import BaseTask

logger = logging.getLogger(__name__)

REPORT_WINDOW_DAYS = 1  # (bugun vs kecha)


@shared_task(base=BaseTask, name="health_ai.generate_daily_reports")
def generate_daily_reports():
    """Har ertalab 06:00 — faol (ACCEPTED) doctor↔patient juftlari uchun kunlik
    AI insight report navbatga qo'yadi (fan-out, har biri alohida subtask)."""
    today = timezone.localdate()
    pairs = DoctorPatient.objects.filter(
        status=DoctorPatient.Status.ACCEPTED
    ).values("doctor_id", "patient_id", "patient_profile_id")

    queued = 0
    for p in pairs:
        if not p["patient_profile_id"]:
            continue  # profil yo'q — kontekst uchun kerak, skip
        try:
            generate_one_report.delay(
                doctor_id=p["doctor_id"],
                patient_id=p["patient_id"],
                patient_profile_id=p["patient_profile_id"],
                period_date=today.isoformat(),
            )
            queued += 1
        except Exception:  # noqa: BLE001 — broker o'chiq bo'lsa skip
            logger.exception("generate_one_report navbatga qo'yilmadi")

    logger.info("Daily AI report: %d juft navbatga qo'yildi", queued)
    return {"queued": queued}


@shared_task(base=BaseTask, bind=True, name="health_ai.generate_one_report")
def generate_one_report(self, doctor_id, patient_id, patient_profile_id, period_date, force=False, language=None):
    from app.health_ai import prompts, services
    from app.health_ai.models import AIHealthReport
    from app.notifications.models import Notification
    from app.notifications.utils import notify
    from services.gemini import generate_text

    period_start = date_cls.fromisoformat(period_date)

    # 1) Idempotent — shu kun uchun report bor bo'lsa skip.
    #    force=True (doctor "Yangilash" bosgani) — qayta generatsiya, update_or_create yangilaydi.
    if not force and AIHealthReport.objects.filter(
        patient_profile_id=patient_profile_id, doctor_id=doctor_id, period_start=period_start
    ).exists():
        return {"skipped": "exists"}

    User = get_user_model()
    patient = User.objects.filter(id=patient_id).first()
    doctor = DoctorProfile.objects.select_related("user").filter(id=doctor_id).first()
    if not patient or not doctor:
        return {"skipped": "no_patient_or_doctor"}

    # 2) Activity-filter — so'nggi oynada data bo'lmasa Gemini chaqirmaymiz (cost)
    window_start = period_start - timedelta(days=REPORT_WINDOW_DAYS)
    has_activity = (
        HealthIndicator.objects.filter(user=patient, date__gte=window_start).exists()
        or DietEntry.objects.filter(user=patient, date__gte=window_start).exists()
        or TreatmentLog.objects.filter(user=patient, date__gte=window_start).exists()
    )
    # force=True bo'lsa activity-filter'ni o'tkazib yuboramiz — doctor ataylab so'radi
    # (bulk 06:00 run uchun filter cost tejaydi, on-demand uchun emas).
    if not force and not has_activity:
        return {"skipped": "no_activity"}

    # 3) Multi-source kontekst + report data
    doctor_user = doctor.user
    # on-demand'da doctor UI tili (request) uzatiladi; 06:00 bulk'da settings tili.
    lang = language or getattr(getattr(doctor_user, "settings", None), "language", None) or "uz"
    context = services.build_patient_context(patient)
    trend = services.build_indicator_trend(patient, months=3)
    report_data = services.build_report_data(patient, window_days=REPORT_WINDOW_DAYS)
    system_prompt = prompts.build_report_system_prompt(lang, context, trend)

    # 4) Gemini (structured JSON, past temp)
    result = generate_text(
        prompt=(
            "Quyidagi ma'lumotlar asosida shifokor uchun bemorning kunlik INSIGHT "
            f"hisobotini bering (klinik tashxis emas):\n\n{report_data}"
        ),
        system_instruction=system_prompt,
        response_schema=prompts.HEALTH_REPORT_SCHEMA,
        temperature=0.3,
    )
    if "error" in result:
        logger.warning("AI report Gemini xato (patient=%s): %s", patient_id, result["error"])
        return {"error": result["error"]}

    parsed = services.parse_report_response(result.get("text") or "")
    if parsed is None:
        logger.warning("AI report parse xato (patient=%s)", patient_id)
        return {"error": "parse"}

    # 5) Upsert (idempotent — yuqoridagi guard + unique constraint backstop)
    report, _ = AIHealthReport.objects.update_or_create(
        patient_profile_id=patient_profile_id,
        doctor_id=doctor_id,
        period_start=period_start,
        defaults={
            "patient_id": patient_id,
            "period_end": period_start,
            "summary": parsed["summary"],
            "detected_changes": parsed["detected_changes"],
            "severity": parsed["severity"],
            "tokens_input": result.get("tokens_input", 0),
            "tokens_output": result.get("tokens_output", 0),
        },
    )

    # 6) Faqat CRITICAL bo'lsa doctorga push (spam emas — qolgani app feed'da jim)
    if report.severity == AIHealthReport.Severity.CRITICAL:
        try:
            notify(
                doctor_user,
                type=Notification.Type.DAILY_AI_REPORT,
                title="Jiddiy AI signal",
                body=f"{patient.full_name or 'Bemor'} — bugungi AI hisobotда jiddiy o'zgarish.",
                data={"report_id": str(report.id), "patient_id": str(patient_id), "severity": report.severity},
                app_scope="doctor",
            )
        except Exception:  # noqa: BLE001 — push o'chiq bo'lsa report baribir saqlanadi
            logger.exception("AI report doctor push xato")

    return {"created": report.id, "severity": report.severity}
