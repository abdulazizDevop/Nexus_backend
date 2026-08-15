"""Tracking AI kontekst/data builder'lari.

Pattern: app/health_ai/services.py (self-contained nusxa — coupling yo'q).
Bemor kuni bo'yicha kompakt matn bloklari tuziladi va Gemini'ga beriladi.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from core.i18n import pick_translation

logger = logging.getLogger("mediik.tracking_ai")

# Klinik diqqat turlari — system_key bo'yicha (health_ai bilan bir xil ro'yxat).
CRITICAL_KEYS = {"blood_pressure", "glucose", "hba1c", "heart_rate", "spo2", "temperature"}

# Faqat HAQIQIY shoshilinch chegaralar (AI grounding; yakuniy baho — AI + shifokor).
SEVERITY_THRESHOLDS = {
    "blood_pressure": {"critical_high": (180, 120), "warning_high": (140, 90)},
    "glucose": {"critical_high": 16.7, "critical_low": 3.0, "warning_high": 11.1},
    "heart_rate": {"critical_high": 150, "critical_low": 40, "warning_high": 120},
    "spo2": {"critical_low": 90, "warning_low": 94},
    "temperature": {"critical_high": 39.5, "warning_high": 38.0},
}


def threshold_hint(system_key, primary, secondary=None) -> str:
    """O'lchov klinik chegaradan chiqqan bo'lsa qisqa hint qaytaradi (aks holda '')."""
    t = SEVERITY_THRESHOLDS.get(system_key)
    if not t or primary is None:
        return ""
    p = float(primary)
    if system_key == "blood_pressure":
        s = float(secondary) if secondary is not None else 0
        ch, cl = t["critical_high"], t["warning_high"]
        if p >= ch[0] or s >= ch[1]:
            return "KRITIK: gipertonik kriz darajasi"
        if p >= cl[0] or s >= cl[1]:
            return "e'tibor: yuqori bosim diapazoni"
        return ""
    if "critical_high" in t and p >= t["critical_high"]:
        return "KRITIK: juda yuqori"
    if "critical_low" in t and p <= t["critical_low"]:
        return "KRITIK: juda past"
    if "warning_high" in t and p >= t["warning_high"]:
        return "e'tibor: yuqori"
    if "warning_low" in t and p <= t["warning_low"]:
        return "e'tibor: past"
    return ""


def build_patient_context(user) -> str:
    """Bemor haqidagi statik kontekst (profil, kasallik, muolajalar)."""
    lines = [f"Ism: {user.full_name or '—'}"]
    if getattr(user, "sex", None):
        lines.append(f"Jins: {'Erkak' if user.sex == 'male' else 'Ayol'}")

    try:
        from app.medical.models import MedicalCard, MedicalCondition

        card = MedicalCard.objects.filter(user=user).first()
        if card and card.primary_disease:
            lines.append(f"Asosiy tashxis: {card.primary_disease}")
        conds = MedicalCondition.objects.filter(user=user)[:10]
        if conds:
            lines.append(
                "Holatlar: " + "; ".join(f"{c.get_type_display()}: {c.name}" for c in conds)
            )
    except ImportError:
        pass

    try:
        from app.treatment.models import Treatment

        active = Treatment.objects.filter(user=user, status=Treatment.Status.ACTIVE)[:15]
        if active:
            lines.append(
                "Aktiv muolajalar: "
                + "; ".join(f"{t.title} ({t.get_type_display()})" for t in active)
            )
    except ImportError:
        pass

    return "\n".join(lines)


def compute_adherence(user, day) -> tuple[int | None, str]:
    """Kun bo'yicha muolaja bajarilishi: (percent | None, matn qatori)."""
    from app.treatment.models import Treatment, TreatmentLog

    total = 0
    done = 0
    skipped = 0
    per_treatment = {}
    completed_logs = TreatmentLog.objects.filter(
        user=user, date=day, status=TreatmentLog.Status.COMPLETED
    )
    for log in completed_logs:
        if log.treatment_id:
            per_treatment[log.treatment_id] = per_treatment.get(log.treatment_id, 0) + 1
    skipped = TreatmentLog.objects.filter(
        user=user, date=day, status=TreatmentLog.Status.SKIPPED
    ).count()

    rows = []
    for t in Treatment.objects.filter(user=user, status=Treatment.Status.ACTIVE):
        if not t._scheduled_on(day):
            continue
        slots = t.slots_per_day() or 1
        d = min(per_treatment.get(t.id, 0), slots)
        total += slots
        done += d
        rows.append(f"  - {t.title}: {d}/{slots}")

    if not total:
        return None, "Bugungi kunga rejalashtirilgan muolaja yo'q."
    percent = int(done * 100 / total)
    text = f"Muolaja bajarilishi: {done}/{total} ({percent}%), o'tkazib yuborilgan: {skipped}\n" + "\n".join(rows)
    return percent, text


def build_tracking_data(user, period_date) -> str:
    """Kun bo'yicha dinamik ma'lumot bloki (ko'rsatkichlar + kayfiyat + adherence)."""
    from app.health_packages.models import DailySituationCheckup, HealthIndicator

    lines = [f"SANA: {period_date.isoformat()}"]

    _, adherence_text = compute_adherence(user, period_date)
    lines.append(adherence_text)

    checkup = DailySituationCheckup.objects.filter(user=user, date=period_date).first()
    if checkup:
        lines.append(f"Kayfiyat: {checkup.get_status_display()}" + (f" ({checkup.note})" if checkup.note else ""))

    yesterday = period_date - timedelta(days=1)
    inds = (
        HealthIndicator.objects.filter(user=user, date__in=[period_date, yesterday])
        .select_related("indicator_type")
        .order_by("recorded_at")
    )
    today_rows, y_rows = [], {}
    for ind in inds:
        key = ind.indicator_type.system_key or pick_translation(ind.indicator_type.name, "uz")
        if ind.date == yesterday:
            y_rows[key] = ind.display_value
            continue
        hint = threshold_hint(
            ind.indicator_type.system_key, ind.value, ind.value_secondary
        )
        prev = y_rows.get(key)
        row = f"  - {pick_translation(ind.indicator_type.name, 'uz')}: {ind.display_value}"
        if ind.indicator_type.unit:
            row += f" {ind.indicator_type.unit}"
        if prev:
            row += f" (kecha: {prev})"
        if hint:
            row += f" [{hint}]"
        today_rows.append(row)
    if today_rows:
        lines.append("Bugungi ko'rsatkichlar:\n" + "\n".join(today_rows))
    else:
        lines.append("Bugun ko'rsatkich kiritilmagan.")

    return "\n\n".join(lines)


def has_activity(user, period_date) -> bool:
    """Kunda hech qanday ma'lumot bormi (bo'lmasa Gemini chaqirmaymiz — cost control)."""
    from app.health_packages.models import DailySituationCheckup, HealthIndicator
    from app.treatment.models import TreatmentLog

    return (
        HealthIndicator.objects.filter(user=user, date=period_date).exists()
        or TreatmentLog.objects.filter(user=user, date=period_date).exists()
        or DailySituationCheckup.objects.filter(user=user, date=period_date).exists()
    )


def parse_tracking_response(raw_text: str):
    """Gemini JSON javobini dict'ga aylantiradi (xato bo'lsa None)."""
    import json

    try:
        data = json.loads(raw_text)
    except (ValueError, TypeError):
        logger.warning("Tracking AI javobi JSON emas: %.200s", raw_text)
        return None
    if not isinstance(data, dict) or "summary" not in data:
        return None
    return data
