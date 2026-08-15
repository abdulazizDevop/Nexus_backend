from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar
from .nutrition import get_daily_summary, resolve_targets

_OBSTACLE_LABEL = {
    "discipline": "intizom yetishmovchiligi",
    "habits": "eski odatlar",
    "support": "qo'llab-quvvatlash yo'qligi",
    "schedule": "vaqt/jadval",
}

_OUTCOME_LABEL = {
    "healthy_eating": "sog'lom ovqatlanish",
    "energy_mood": "energiya va kayfiyat",
    "motivation_discipline": "motivatsiya va intizom",
    "body_look": "tashqi ko'rinish",
}

def build_user_context(user) -> str:
    """Bemor profilini AI prompt uchun string ko'rinishda qaytaradi.

    O'z ichiga oladi:
        - Asosiy ma'lumotlar (yosh, jins, vazn, bo'y)
        - Oxirgi salomatlik ko'rsatkichlari
        - Surunkali kasalliklar
        - Doctor belgilagan cheklovlar (DietRestriction)
        - Hozirgi aktiv muolajalar
        - Kunlik kaloriya chegarasi + bugungi iste'mol
    """
    parts = []

    # --- Asosiy profil ---
    name = user.full_name or "Bemor"
    sex_map = {"male": "erkak", "female": "ayol"}
    sex = sex_map.get(user.sex, "")

    age = None
    if user.birth_date:
        today = date.today()
        age = today.year - user.birth_date.year
        if (today.month, today.day) < (user.birth_date.month, user.birth_date.day):
            age -= 1

    profile_line = f"Ism: {name}"
    if sex:
        profile_line += f", {sex}"
    if age is not None:
        profile_line += f", {age} yosh"
    parts.append(profile_line)

    # --- Medical card (qon guruhi, asosiy kasallik) ---
    card = MedicalCard.objects.filter(user=user).first()
    if card:
        med_parts = []
        if getattr(card, "blood_type", None):
            med_parts.append(f"qon guruhi: {card.blood_type}")
        if getattr(card, "primary_disease", None):
            med_parts.append(f"asosiy kasallik: {card.primary_disease}")
        if med_parts:
            parts.append("Tibbiy karta: " + ", ".join(med_parts))

    # --- Salomatlik ko'rsatkichlari (har turdagi oxirgi qiymat) ---
    user_lang = (
        getattr(getattr(user, "settings", None), "language", None) or "uz"
    )
    seen = {}
    for ind in (
        HealthIndicator.objects.filter(user=user)
        .select_related("indicator_type")
        .order_by("-recorded_at")[:50]
    ):
        if ind.indicator_type_id not in seen:
            seen[ind.indicator_type_id] = ind
    if seen:
        # JSON field — pick_translation bilan user tilida ko'rsatiladi
        # (str(dict) yuborilsa AI sifati pasayadi).
        ind_lines = [
            f"{pick_translation(ind.indicator_type.name, user_lang)}: "
            f"{ind.display_value} {ind.indicator_type.unit}"
            for ind in seen.values()
        ]
        parts.append("Oxirgi ko'rsatkichlar: " + "; ".join(ind_lines))

    # --- Parhez maqsadi + kunlik target + bugungi qoldiq ---
    diet_profile = DietProfile.objects.filter(user=user).first()
    if diet_profile:
        parts.append(f"Parhez maqsadi: {diet_profile.get_goal_display()}")
        if diet_profile.restrictions:
            parts.append("Ovqat cheklovlari: " + ", ".join(diet_profile.restrictions))
        if diet_profile.obstacles:
            obs = [_OBSTACLE_LABEL.get(o, o) for o in diet_profile.obstacles]
            parts.append(
                "To'siqlar (tavsiya OHANGINI shunga moslang — ayblovsiz, kichik qadamli): "
                + ", ".join(obs)
            )
        if diet_profile.outcomes:
            outs = [_OUTCOME_LABEL.get(o, o) for o in diet_profile.outcomes]
            parts.append("Istaklar (tavsiya FOKUSI): " + ", ".join(outs))
    targets = resolve_targets(user, date.today())
    src_label = {
        "doctor": "shifokor belgilagan",
        "auto": "profil asosida",
        "default": "standart",
    }.get(targets["source"], "")
    parts.append(
        f"Kunlik norma ({src_label}): {targets['calories']} kcal "
        f"(O:{targets['protein_g']}g U:{targets['carbs_g']}g Y:{targets['fat_g']}g)"
    )
    today_summary = get_daily_summary(user, date.today())
    cal = today_summary.get("calories", {})
    if cal.get("remaining") is not None:
        parts.append(f"Bugun qolgan kaloriya: {cal['remaining']} kcal")

    # --- Kasalliklar + allergiya ---
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

    # --- Hozirgi aktiv muolajalar ---
    treatments = Treatment.objects.filter(
        user=user, status=Treatment.Status.ACTIVE
    ).order_by("time")[:10]
    if treatments:
        t_lines = [f"{t.title} ({t.get_type_display()})" for t in treatments]
        parts.append("Hozirgi muolajalar: " + "; ".join(t_lines))

    # --- Doctor cheklovlari ---
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
        parts.append("⚠️ Doctor cheklovlari: " + "; ".join(rest_lines))

    return "\n".join(f"- {p}" for p in parts)


# ---------------------------------------------------------------------------
# Target hisoblagich (kaloriya + makro) — FAQAT backend. Ustunlik:
# doctor (DailyCalorieLimit) > auto (profil formulasi) > default (2000).
# ---------------------------------------------------------------------------
