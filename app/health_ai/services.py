"""Health AI xizmatlari — kontekst, ko'rsatkich trendi, period aggregation,
severity, chat helperlari. Report (kunlik) va doctor↔AI chat ikkalasi ham ishlatadi.

Pattern manbai: app/diet_ai/services.py (self-contained nusxa — coupling yo'q).
"""

import json
from datetime import date as date_cls
from datetime import timedelta

from django.db.models import Avg, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core.i18n import pick_translation

from app.health_packages.models import HealthIndicator, HealthIndicatorType
from app.medical.models import MedicalCard, MedicalCondition
from app.treatment.models import DailyCalorieLimit, Treatment, TreatmentLog
from app.diet_ai.models import DietEntry, DietRestriction

MAX_HISTORY_MESSAGES = 12          # chat — Gemini'ga oxirgi N xabar
MAX_MESSAGES_PER_CONVERSATION = 40  # shu chegaraga yetsa yangi suhbat tavsiyasi


# ===========================================================================
# Bemor konteksti (chat + report) — diet_ai.build_user_context nusxasi
# ===========================================================================

def build_patient_context(user) -> str:
    """Bemor profilini AI prompt uchun string ko'rinishda qaytaradi.

    Profil + medical card + oxirgi ko'rsatkichlar + kaloriya chegarasi +
    kasalliklar/allergiya + aktiv muolajalar + doctor cheklovlari.
    """
    parts = []

    name = user.full_name or "Bemor"
    sex_map = {"male": "erkak", "female": "ayol"}
    sex = sex_map.get(getattr(user, "sex", None), "")

    age = None
    if getattr(user, "birth_date", None):
        today = date_cls.today()
        age = today.year - user.birth_date.year
        if (today.month, today.day) < (user.birth_date.month, user.birth_date.day):
            age -= 1

    profile_line = f"Ism: {name}"
    if sex:
        profile_line += f", {sex}"
    if age is not None:
        profile_line += f", {age} yosh"
    parts.append(profile_line)

    card = MedicalCard.objects.filter(user=user).first()
    if card:
        med_parts = []
        if getattr(card, "blood_type", None):
            med_parts.append(f"qon guruhi: {card.blood_type}")
        if getattr(card, "primary_disease", None):
            med_parts.append(f"asosiy kasallik: {card.primary_disease}")
        if med_parts:
            parts.append("Tibbiy karta: " + ", ".join(med_parts))

    user_lang = getattr(getattr(user, "settings", None), "language", None) or "uz"

    # Har turdan oxirgi 1 qiymat (snapshot)
    seen = {}
    for ind in (
        HealthIndicator.objects.filter(user=user)
        .select_related("indicator_type")
        .order_by("-recorded_at")[:50]
    ):
        if ind.indicator_type_id not in seen:
            seen[ind.indicator_type_id] = ind
    if seen:
        ind_lines = [
            f"{pick_translation(ind.indicator_type.name, user_lang)}: "
            f"{ind.display_value} {ind.indicator_type.unit}"
            for ind in seen.values()
        ]
        parts.append("Oxirgi ko'rsatkichlar: " + "; ".join(ind_lines))

    limit = DailyCalorieLimit.objects.filter(patient=user).first()
    if limit:
        parts.append(f"Kunlik kaloriya chegarasi (doctor): {limit.calories} kcal")

    # Oxirgi ovqat-yozuvlari (food photo / qo'lda) — AI bemor AYNAN nima
    # yeyayotganini bilishi uchun. Bo'lmasa faqat ozuqa ko'rsatkichlari bo'lib,
    # "ovqat ma'lumoti yo'q" deb javob berardi.
    foods = list(
        DietEntry.objects.filter(user=user).order_by("-date", "-created_at")[:20]
    )
    if foods:
        food_lines = [
            f"{f.date.strftime('%d.%m')} {f.food_name} "
            f"({f.calories} kcal; O{f.protein_grams}/U{f.carbs_grams}/Y{f.fat_grams}g)"
            for f in foods
        ]
        parts.append("Oxirgi ovqatlar (ovqat-log): " + "; ".join(food_lines))

    conds = MedicalCondition.objects.filter(user=user).order_by("-created_at")[:10]
    if conds:
        cond_lines = []
        for c in conds:
            line = f"{c.get_type_display()}: {c.name}"
            sev = c.get_severity_display() if c.severity else ""
            if sev:
                line += f" ({sev})"
            cond_lines.append(line)
        parts.append("Kasalliklar/allergiya: " + "; ".join(cond_lines))

    treatments = Treatment.objects.filter(
        user=user, status=Treatment.Status.ACTIVE
    ).order_by("time")[:10]
    if treatments:
        t_lines = [f"{t.title} ({t.get_type_display()})" for t in treatments]
        parts.append("Hozirgi muolajalar: " + "; ".join(t_lines))

    restrictions = DietRestriction.objects.filter(
        patient=user, is_active=True
    ).order_by("-created_at")[:10]
    if restrictions.exists():
        rest_lines = []
        for r in restrictions:
            line = r.rule
            if r.reason:
                line += f" ({r.reason})"
            rest_lines.append(line)
        parts.append("Doctor cheklovlari: " + "; ".join(rest_lines))

    return "\n".join(f"- {p}" for p in parts)


# ===========================================================================
# Ko'rsatkich trendi (oylik o'rtacha) — multi-oy chuqur tahlil
# ===========================================================================

def build_indicator_trend(user, months: int = 3) -> str:
    """Har indicator turi bo'yicha oylik o'rtacha (oxirgi `months` oy) — trend matni."""
    since = timezone.localdate() - timedelta(days=months * 31)
    rows = (
        HealthIndicator.objects.filter(user=user, date__gte=since)
        .select_related("indicator_type")
        .annotate(m=TruncMonth("date"))
        .values("indicator_type_id", "indicator_type__name", "indicator_type__unit", "m")
        .annotate(avg=Avg("value"))
        .order_by("indicator_type_id", "m")
    )
    if not rows:
        return ""

    user_lang = getattr(getattr(user, "settings", None), "language", None) or "uz"
    grouped: dict[int, dict] = {}
    for r in rows:
        g = grouped.setdefault(
            r["indicator_type_id"],
            {"name": r["indicator_type__name"], "unit": r["indicator_type__unit"] or "", "points": []},
        )
        if r["avg"] is not None and r["m"] is not None:
            g["points"].append((r["m"].strftime("%Y-%m"), round(float(r["avg"]), 1)))

    lines = []
    for g in grouped.values():
        if not g["points"]:
            continue
        name = pick_translation(g["name"], user_lang)
        seq = ", ".join(f"{m}: {v}{g['unit']}" for m, v in g["points"])
        lines.append(f"- {name}: {seq}")
    return "\n".join(lines)


# ===========================================================================
# Period aggregation (hafta/davr o'rtacha + oxirgi) — report delta uchun
# ===========================================================================

def period_aggregate(user_id, indicator_type_id, start, end) -> dict:
    """[start, end) oralig'idagi o'rtacha (primary+secondary) + oxirgi qiymat + count."""
    qs = HealthIndicator.objects.filter(
        user_id=user_id,
        indicator_type_id=indicator_type_id,
        date__gte=start,
        date__lt=end,
    )
    agg = qs.aggregate(avg_primary=Avg("value"), avg_secondary=Avg("value_secondary"))
    latest = qs.order_by("-recorded_at").values("value", "value_secondary").first()
    return {
        "count": qs.count(),
        "avg_primary": agg["avg_primary"],
        "avg_secondary": agg["avg_secondary"],
        "latest_primary": latest["value"] if latest else None,
        "latest_secondary": latest["value_secondary"] if latest else None,
    }


# ===========================================================================
# Severity threshold (rule-based grounding — AI promptga beriladi)
# ===========================================================================

# Klinik diqqat turlari (severity prioriteti). system_key bo'yicha (category emas).
CRITICAL_KEYS = {"blood_pressure", "glucose", "hba1c", "heart_rate", "spo2", "temperature"}

# Klinik chegaralar (AI grounding uchun; yakuniy baho — AI + shifokor).
# MUHIM: `critical` = HAQIQIY shoshilinch/xavfli (kriz darajasi), `warning` = e'tibor
# talab (kasallik diapazoni). Aks holda har normal-yuqori o'lchov "Jiddiy" bo'lib
# alert-fatigue keltiradi (masalan 126/91 — bu kriz emas, 2-daraja gipertenziya).
SEVERITY_THRESHOLDS = {
    # warn = 2-daraja gipertenziya (≥140/90), crit = gipertonik kriz (≥180/120)
    "blood_pressure": {"sys_warn": 140, "sys_crit": 180, "dia_warn": 90, "dia_crit": 120},
    # mmol/L: warn = diabet diapazoni, crit = og'ir giper; low = gipoglikemiya
    "glucose": {"high_warn": 7.0, "high_crit": 13.0, "low_warn": 3.9, "low_crit": 3.0},
    "spo2": {"low_warn": 94, "low_crit": 90},
    "temperature": {"high_warn": 37.5, "high_crit": 39.0},
    "heart_rate": {"high_warn": 100, "high_crit": 140, "low_warn": 50, "low_crit": 45},
    "hba1c": {"high_warn": 6.5, "high_crit": 8.0},
}


def threshold_hint(system_key, primary, secondary=None) -> str:
    """FAQAT haqiqiy shoshilinch/xavfli darajani belgilaydi — absolyut xavfsizlik
    chizig'i (gipertonik kriz, og'ir gipo/giper, kritik SpO2, yuqori isitma, xavfli puls).

    Sub-kritik baho AI'ga qoldiriladi: AI qiymatni bemorning O'Z o'rtachasi/trendiga
    solishtirib personalizatsiya qiladi ('shundan oshsa yomon' qat'iy qoidasi emas).
    Sabab: bemor bazaviy holati patologik bo'lsa (surunkali 180/110), faqat o'rtachaga
    qarab baholasak xavfli barqaror qiymatni mutlaqo o'tkazib yuborardik — shuning uchun
    kriz darajasi qattiq qoida bo'lib qoladi."""
    th = SEVERITY_THRESHOLDS.get(system_key)
    if th is None or primary is None:
        return ""
    p = float(primary)
    if system_key == "blood_pressure":
        d = float(secondary) if secondary is not None else None
        if p >= th["sys_crit"] or (d is not None and d >= th["dia_crit"]):
            return "gipertonik kriz darajasi (critical)"
    elif system_key in ("glucose", "hba1c"):
        if p >= th.get("high_crit", 1e9):
            return "juda yuqori (critical)"
        if "low_crit" in th and p < th["low_crit"]:
            return "og'ir gipoglikemiya (critical)"
    elif system_key == "spo2":
        if p < th["low_crit"]:
            return "past kislorod (critical)"
    elif system_key == "temperature":
        if p >= th["high_crit"]:
            return "yuqori isitma (critical)"
    elif system_key == "heart_rate":
        if p >= th["high_crit"] or p <= th["low_crit"]:
            return "xavfli puls (critical)"
    return ""


# ===========================================================================
# Chat helperlari (diet_ai nusxasi) — har conversation `.messages` (role/content/is_blocked)
# ===========================================================================

def should_suggest_new_chat(conversation) -> bool:
    return conversation.messages.count() >= MAX_MESSAGES_PER_CONVERSATION


def build_history_for_ai(conversation, limit: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    """Oldingi xabarlar Gemini formatida: [{"role": "user|model", "text": ...}] (oxirgi N)."""
    messages = list(
        reversed(
            list(
                conversation.messages.exclude(is_blocked=True)
                .order_by("-created_at")[:limit]
            )
        )
    )
    history = []
    for msg in messages:
        if msg.role == "user":
            history.append({"role": "user", "text": msg.content})
        elif msg.role == "assistant":
            history.append({"role": "model", "text": msg.content})
    return history


def auto_generate_title(first_question: str, max_length: int = 60) -> str:
    clean = first_question.strip().replace("\n", " ")
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 3] + "..."


# ===========================================================================
# Behavioral signallar (ovqat-log / parhez / muolaja adherence / engagement)
# ===========================================================================

def build_behavioral_signals(user, days: int = 7) -> str:
    """Insight uchun xulq-atvor signallari: ovqat-log xulqi, parhez, muolaja, engagement."""
    today = timezone.localdate()
    start = today - timedelta(days=days)
    prev_start = start - timedelta(days=days)
    lines = []

    # 1) Ovqat-log xulqi (rasm)
    last_entry = (
        DietEntry.objects.filter(user=user).order_by("-date").values_list("date", flat=True).first()
    )
    if last_entry is None:
        lines.append("Ovqat-log: hech qachon ovqat kiritmagan")
    else:
        gap = (today - last_entry).days
        photo_recent = DietEntry.objects.filter(
            user=user, date__gte=start, source=DietEntry.Source.AI_PHOTO
        ).count()
        photo_prev = DietEntry.objects.filter(
            user=user, date__gte=prev_start, date__lt=start, source=DietEntry.Source.AI_PHOTO
        ).count()
        if gap >= 3:
            lines.append(f"Ovqat-log: oxirgi yozuv {gap} kun oldin — ovqat rasmini yuklamayapti")
        else:
            lines.append(
                f"Ovqat-log (rasm): so'nggi {days} kun {photo_recent} ta "
                f"(oldingi {days} kun {photo_prev} ta)"
            )

    # 2) Parhez (kunlik kaloriya vs doctor limiti)
    limit = (
        DailyCalorieLimit.objects.filter(patient=user).values_list("calories", flat=True).first()
    )
    if limit:
        per_day = (
            DietEntry.objects.filter(user=user, date__gte=start)
            .values("date").annotate(total=Sum("calories"))
        )
        over_days = sum(1 for d in per_day if d["total"] and d["total"] > limit)
        if over_days:
            lines.append(
                f"Parhez: so'nggi {days} kunda {over_days} kun kaloriya limitidan "
                f"({limit} kcal) oshgan — parhez buzilvotti"
            )
        elif per_day:
            lines.append(f"Parhez: kaloriya limiti ({limit} kcal) doirasida")

    # 3) Muolaja adherence
    logs = TreatmentLog.objects.filter(user=user, date__gte=start)
    completed = logs.filter(status=TreatmentLog.Status.COMPLETED).count()
    skipped = logs.filter(status=TreatmentLog.Status.SKIPPED).count()
    if completed or skipped:
        line = f"Muolaja: so'nggi {days} kun bajarildi {completed}, o'tkazib yuborildi {skipped}"
        if skipped >= 2 and skipped >= completed:
            line += " — adherence past"
        lines.append(line)

    # 4) Engagement (oxirgi ko'rsatkich/faollik)
    last_ind = (
        HealthIndicator.objects.filter(user=user).order_by("-recorded_at")
        .values_list("date", flat=True).first()
    )
    if last_ind:
        igap = (today - last_ind).days
        if igap >= 3:
            lines.append(f"Engagement: oxirgi ko'rsatkich {igap} kun oldin")

    return "\n".join(f"- {ln}" for ln in lines) if lines else "- (faollik ma'lumoti yo'q)"


def build_report_data(user, window_days: int = 7) -> str:
    """Kunlik report uchun AI input: indikator delta (so'nggi N kun vs oldingi N kun)
    + threshold grounding + behavioral signallar. Rolling oyna — har kun yangilanadi."""
    today = timezone.localdate()
    cur_start = today - timedelta(days=window_days)
    prev_start = cur_start - timedelta(days=window_days)
    user_lang = getattr(getattr(user, "settings", None), "language", None) or "uz"

    type_ids = list(
        HealthIndicator.objects.filter(user=user, date__gte=cur_start)
        .values_list("indicator_type_id", flat=True).distinct()
    )
    types = {t.id: t for t in HealthIndicatorType.objects.filter(id__in=type_ids)}

    lines = []
    for tid in type_ids:
        itype = types.get(tid)
        if not itype:
            continue
        cur = period_aggregate(user.id, tid, cur_start, today + timedelta(days=1))
        if cur["avg_primary"] is None:
            continue
        prev = period_aggregate(user.id, tid, prev_start, cur_start)
        name = pick_translation(itype.name, user_lang)
        unit = itype.unit or ""
        cur_v = round(float(cur["avg_primary"]), 1)
        # Qon bosimi — sistolik/diastolik ikkalasini ko'rsatamiz (faqat sistolik
        # chalg'itadi: 124 sistolik gipertenziya emas, lekin 91 diastolik muhim).
        is_bp = itype.system_key == "blood_pressure"
        cur_sec = cur.get("avg_secondary")
        cur_disp = f"{cur_v}/{round(float(cur_sec), 1)}" if (is_bp and cur_sec is not None) else f"{cur_v}"
        if window_days == 1:
            line = f"{name}: bugun {cur_disp}{unit}"
            prev_label = "kecha"
        else:
            line = f"{name}: so'nggi {window_days} kun o'rtacha {cur_disp}{unit}"
            prev_label = "oldingi"
        if prev["avg_primary"] is not None:
            prev_v = round(float(prev["avg_primary"]), 1)
            prev_sec = prev.get("avg_secondary")
            prev_disp = f"{prev_v}/{round(float(prev_sec), 1)}" if (is_bp and prev_sec is not None) else f"{prev_v}"
            line += f" ({prev_label}: {prev_disp}{unit}, Δ{cur_v - prev_v:+.1f})"
        hint = threshold_hint(itype.system_key, cur["latest_primary"], cur["latest_secondary"])
        if hint:
            line += f" [{hint}]"
        lines.append(f"- {line}")

    indicator_block = "\n".join(lines) if lines else "- (bugun ko'rsatkich yo'q)"
    behavioral = build_behavioral_signals(user, days=window_days)
    period_label = "bugun" if window_days == 1 else f"so'nggi {window_days} kun"
    return (
        f"KO'RSATKICHLAR ({period_label}):\n{indicator_block}\n\n"
        f"XULQ-ATVOR SIGNALLARI:\n{behavioral}"
    )


def parse_report_response(raw_text: str):
    """Gemini structured report JSON'ini parse qiladi. Schema majburiy bo'lgani uchun
    odatda toza JSON; xato bo'lsa None (chaqiruvchi skip qiladi)."""
    raw = (raw_text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    changes = data.get("detected_changes")
    return {
        "summary": (data.get("summary") or "").strip(),
        "detected_changes": changes if isinstance(changes, list) else [],
        "severity": data.get("severity") or "normal",
    }
