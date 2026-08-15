"""Bemor holati konteksti — AI gapirishdan OLDIN uni "ko'radi".

`build_patient_context(user)` bemorning holatini VAQT-XABARDOR yig'adi:
- Dori: faqat vaqti O'TIB KETGAN dozalarni "ichilmagan" deydi; vaqti kelmaganini EMAS.
- Uyqu: eski (kechagi) yozuvni bugungidek ko'rsatmaydi — sanasini belgilaydi.
- Ovqat: kun vaqtiga qarab (ertalab/tushlik/kechki) o'tib ketgan mahalni ajratadi.

Har bo'lim alohida try/except — bitta app xato bersa/o'zgarsa qolgani ishlayveradi.
"""

import logging

from django.db.models import Count, Sum
from django.utils import timezone

logger = logging.getLogger("mediik.voice_ai")


def _diet_line(user, today, now) -> str | None:
    from app.diet_ai.models import DietEntry
    from app.diet_ai.services import get_daily_summary

    entries = list(DietEntry.objects.filter(user=user, date=today))
    count = len(entries)
    photos = sum(1 for e in entries if e.source == DietEntry.Source.AI_PHOTO)

    def meal_of(e):
        if e.meal_type:
            return e.meal_type
        h = timezone.localtime(e.created_at).hour  # meal_type bo'sh → soatdan
        if h < 11:
            return DietEntry.MealType.BREAKFAST
        if h < 16:
            return DietEntry.MealType.LUNCH
        if h < 22:
            return DietEntry.MealType.DINNER
        return DietEntry.MealType.SNACK

    logged = {meal_of(e) for e in entries}
    now_h = now.hour
    # (meal_type, label, tugash_soati) — shu soatdan keyin "vaqti o'tgan"
    windows = [
        (DietEntry.MealType.BREAKFAST, "ertalabki", 11),
        (DietEntry.MealType.LUNCH, "tushlik", 16),
        (DietEntry.MealType.DINNER, "kechki", 22),
    ]
    missed = [lbl for mt, lbl, end_h in windows if now_h >= end_h and mt not in logged]

    if count == 0:
        line = "- Ovqat: bugun hali HECH NARSA kiritilmagan."
        if missed:
            line += f" Vaqti o'tib ketgan mahal(lar): {', '.join(missed)} — kiritilmagan."
    else:
        line = f"- Ovqat: bugun {count} marta kiritilgan (rasmga olingan: {photos})."
        if missed:
            line += f" LEKIN {', '.join(missed)} ovqat kiritilmagan (vaqti o'tgan)."

    try:
        cal = get_daily_summary(user, today).get("calories", {})
        consumed, limit = cal.get("consumed"), cal.get("limit")
        if limit and consumed is not None:
            line += f" Kaloriya: {int(consumed)}/{int(limit)}."
    except Exception:  # noqa: BLE001
        pass
    return line


def _treatment_line(user, today, now) -> list[str]:
    from app.treatment.models import Treatment, TreatmentLog

    active = list(
        Treatment.objects.filter(
            user=user, status=Treatment.Status.ACTIVE
        ).exclude(is_as_needed=True)
    )

    # Bugungi COMPLETED log soni — HAR treatment uchun alohida COUNT (N+1) o'rniga
    # bitta agregat so'rov: {treatment_id: count}.
    taken_by_treatment = {
        row["treatment_id"]: row["n"]
        for row in TreatmentLog.objects.filter(
            treatment__in=active,
            date=today,
            status=TreatmentLog.Status.COMPLETED,
        )
        .values("treatment_id")
        .annotate(n=Count("id"))
    }

    now_t = now.time()
    due_total = 0  # vaqti kelgan/o'tgan dozalar
    taken_total = 0
    upcoming = 0  # hali vaqti kelmagan
    missed = []
    for t in active:
        if not t.is_scheduled_today():
            continue
        times = t.get_scheduled_times() or ([t.time] if t.time else [])
        due = [tm for tm in times if tm and tm <= now_t]
        future = [tm for tm in times if tm and tm > now_t]
        taken = taken_by_treatment.get(t.id, 0)
        due_total += len(due)
        taken_total += min(taken, len(due))
        upcoming += len(future)
        if len(due) > taken:
            missed.append(t.title)

    if due_total == 0 and upcoming == 0:
        return []
    if due_total == 0:
        return [
            f"- Muolaja: bugun {upcoming} doza rejalashtirilgan, lekin HALI birontasi "
            "vaqti kelmagan — ichish haqida so'rama/koyimA."
        ]
    line = f"- Muolaja: vaqti kelgan {due_total} dozadan {taken_total} tasi ichilgan."
    if missed:
        line += f" Vaqti O'TIB KETGAN, ichilmagan: {', '.join(missed[:4])}."
    if upcoming:
        line += f" (Yana {upcoming} doza keyinroq — hali vaqti kelmagan, buni so'rama.)"
    return [line]


def _health_lines(user, today, now) -> list[str]:
    from app.health_packages.models import (
        DailySituationCheckup,
        HealthIndicator,
        HealthIndicatorType,
    )

    out = []

    sleep_type = HealthIndicatorType.objects.filter(system_key="sleep").first()
    if sleep_type:
        last = (
            HealthIndicator.objects.filter(user=user, indicator_type=sleep_type)
            .order_by("-recorded_at")
            .first()
        )
        if last:
            rec_date = last.date or timezone.localtime(last.recorded_at).date()
            days_ago = (today - rec_date).days
            hours = round(float(last.value) / 60, 1)  # sleep — MINUTLARda saqlanadi
            if days_ago <= 0:
                line = f"- Uyqu (so'nggi tun): {hours} soat."
                if hours < 6:
                    line += " Kam uxlagan."
            elif days_ago == 1:
                line = (
                    f"- Uyqu: so'nggi yozuv KECHA ({hours} soat). Bugungi tun uchun "
                    "ma'lumot YO'Q — eski raqamni bugungidek gapirma."
                )
            else:
                line = (
                    f"- Uyqu: so'nggi yozuv {days_ago} kun oldin ({hours} soat) — "
                    "eski, yangi ma'lumot yo'q."
                )
            out.append(line)

    steps_type = HealthIndicatorType.objects.filter(system_key="steps").first()
    if steps_type:
        steps = (
            HealthIndicator.objects.filter(
                user=user, indicator_type=steps_type, date=today
            ).aggregate(t=Sum("value"))["t"]  # qadam — kunlik YIG'INDI
            or 0
        )
        if steps:
            out.append(f"- Bugungi qadam: {int(steps)}.")

    weight_type = HealthIndicatorType.objects.filter(system_key="weight").first()
    if weight_type:
        w = (
            HealthIndicator.objects.filter(user=user, indicator_type=weight_type)
            .order_by("-recorded_at")
            .first()
        )
        if w:
            out.append(f"- Vazn: {float(w.value)} kg.")

    mood = (
        DailySituationCheckup.objects.filter(user=user, date=today)
        .order_by("-id")
        .first()
    )
    if mood:
        label = {"good": "yaxshi", "normal": "o'rtacha", "bad": "yomon"}.get(
            mood.status, mood.status
        )
        out.append(f"- Bugungi kayfiyat: {label}.")

    return out


def _tracking_line(user, today, now) -> list[str]:
    """Oxirgi AI kuzatuv hisoboti (tracking_ai) — bemor so'rasa gapirish uchun."""
    try:
        from app.tracking_ai.models import AITrackingReport
    except ImportError:  # app hali yo'q bo'lsa qolgan kontekst ishlayveradi
        return []

    report = (
        AITrackingReport.objects.filter(patient=user)
        .order_by("-period_start")
        .first()
    )
    if not report:
        return []
    days_ago = (today - report.period_start).days
    if days_ago > 2:
        return []  # eski hisobot — bugungidek gapirmasin

    when = {0: "bugungi", 1: "kechagi"}.get(days_ago, f"{days_ago} kun oldingi")
    sev = {
        "normal": "normal",
        "attention": "e'tibor talab",
        "critical": "JIDDIY",
    }.get(report.severity, report.severity)
    line = f"- AI kuzatuv ({when} hisobot, holat: {sev}): {report.summary[:200]}"
    if report.adherence_percent is not None:
        line += f" Muolaja intizomi: {report.adherence_percent}%."
    out = [line]
    if report.severity == "critical":
        out.append(
            "- MUHIM: AI kuzatuvda JIDDIY holat belgilangan — bemorga yumshoq, "
            "lekin aniq qilib shifokorga murojaatni eslat."
        )
    return out


def build_patient_context(user) -> str:
    """Bemor holati bloki (bo'sh bo'lsa '') — VAQT-XABARDOR."""
    now = timezone.localtime()  # settings TIME_ZONE = Asia/Tashkent
    today = now.date()
    lines: list[str] = []

    name = (user.full_name or "").strip().split(" ")[0]
    if name:
        lines.append(f"- Ism: {name}")

    for section in (_diet_line, _treatment_line, _health_lines, _tracking_line):
        try:
            res = section(user, today, now)
        except Exception as exc:  # noqa: BLE001 — bir bo'lim xatosi qolganini buzmasin
            logger.warning("patient_context %s failed: %s", section.__name__, exc)
            continue
        if isinstance(res, list):
            lines.extend(res)
        elif res:
            lines.append(res)

    # Ism yolg'iz qolsa (haqiqiy data yo'q) — kontekst bermaymiz
    if all(line.startswith("- Ism") for line in lines):
        return ""

    header = (
        f"BEMOR HOZIRGI HOLATI (HOZIRGI VAQT: {now.strftime('%H:%M')}). Shu ANIQ "
        "FAKTLARga qarab gapir — umumiy emas, aynan shu raqamlarni ishlat:"
    )
    footer = (
        "MUHIM VAQT QOIDALARI: (1) Faqat vaqti O'TIB KETGAN dori/ovqat haqida koyi — "
        "vaqti hali KELMAGAN narsani so'rama/eslatma. (2) \"eski\"/\"kecha\" deb "
        "belgilangan ma'lumotni BUGUNgidek gapirma (masalan kechagi uyquni bugungidek "
        "dema). (3) Faktlarni to'qib chiqarma — faqat yuqoridagilarni ishlat; ma'lumot "
        "yo'q joyni umumiy so'ra."
    )
    return f"{header}\n" + "\n".join(lines) + f"\n{footer}"
