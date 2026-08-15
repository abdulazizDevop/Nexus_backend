from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

_ACTIVITY_COEFF = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "high": 1.725,
    "very_high": 1.9,
}

# (protein%, uglevod%, yog'%) — kkal ulushi

_MACRO_SPLIT = {
    "lose": (30, 40, 30),
    "muscle": (30, 45, 25),
    "diabet": (25, 40, 35),  # past-GI urg'u
    "default": (20, 50, 30),
}

# Har-mahal % (kunlik kkal ulushi)
# Har-mahal kaloriya taqsimoti (% kunlik kkal). Xronobiologiya: insulin
# sezuvchanligi ertalab yuqori → nonushta/tushlik katta, kechki ovqat ≤30%
# (2 mahalda ≤45%). Eng katta ulush — tushlik yoki nonushta, hech qachon kechki.
# Manba: Jakubowicz 2013 (Obesity) + 2023 meta-analiz. Mobil wizard preview
# (diet_profile_mock_datasource.dart) shu jadvalga mos.

_MEAL_SPLIT = {
    "two": [("breakfast", 55), ("dinner", 45)],
    "three": [("breakfast", 30), ("lunch", 40), ("dinner", 30)],
    "three_snack": [("breakfast", 30), ("lunch", 35), ("dinner", 25), ("snack", 10)],
    "four": [("breakfast", 25), ("lunch", 35), ("dinner", 25), ("snack", 15)],
    "five_plus": [("breakfast", 25), ("lunch", 30), ("dinner", 25), ("snack", 10), ("snack", 10)],
}

_DEFAULT_CALORIES = 2000

_DIABETES_KEYWORDS = ("diabet", "qand", "shakar", "saxar", "сахар", "диабет")

def _user_age(user):
    if not user.birth_date:
        return None
    today = date.today()
    age = today.year - user.birth_date.year
    if (today.month, today.day) < (user.birth_date.month, user.birth_date.day):
        age -= 1
    return age

def _has_diabetes(user) -> bool:
    names = MedicalCondition.objects.filter(user=user).values_list("name", flat=True)
    joined = " ".join(n.lower() for n in names if n)
    return any(k in joined for k in _DIABETES_KEYWORDS)

def _split_macros(calories: int, split, weight_kg=None, protein_floor_gkg=None):
    p_pct, c_pct, f_pct = split
    protein_g = round(calories * p_pct / 100 / 4)
    carbs_g = round(calories * c_pct / 100 / 4)
    fat_g = round(calories * f_pct / 100 / 9)
    if protein_floor_gkg and weight_kg:
        protein_g = max(protein_g, round(protein_floor_gkg * float(weight_kg)))
    return carbs_g, protein_g, fat_g

def resolve_targets(user, target_date=None) -> dict:
    """Kunlik target (kaloriya + makro + har-mahal). Ustunlik: doctor > auto > default.

    Returns: {source, calories, carbs_g, protein_g, fat_g, per_meal[], explanation, warning}
    """
    limit = DailyCalorieLimit.objects.filter(patient=user).first()
    profile = DietProfile.objects.filter(user=user).first()
    card = MedicalCard.objects.filter(user=user).first()
    weight = card.weight_kg if card and card.weight_kg else None
    height = card.height_cm if card and card.height_cm else None
    age = _user_age(user)
    sex = user.sex if user.sex in ("male", "female") else None
    goal = profile.goal if profile else None
    warning = None

    # --- Makro split tanlash (doctor makrolarini o'rnatmaganда ishlatiladi) ---
    if goal == "muscle":
        split = _MACRO_SPLIT["muscle"]
    elif goal == "lose":
        split = _MACRO_SPLIT["lose"]
    elif goal == "condition" or _has_diabetes(user):
        split = _MACRO_SPLIT["diabet"]
    else:
        split = _MACRO_SPLIT["default"]

    # --- 1) Doctor tier ---
    if limit and limit.calories:
        source = "doctor"
        calories = int(limit.calories)
        if limit.carbs_limit and limit.protein_limit and limit.fat_limit:
            carbs_g, protein_g, fat_g = (
                int(limit.carbs_limit),
                int(limit.protein_limit),
                int(limit.fat_limit),
            )
        else:
            carbs_g, protein_g, fat_g = _split_macros(calories, split, weight)
        explanation = "Shifokoringiz belgilagan norma"
    # --- 2) Auto tier (profil to'liq) ---
    elif profile and weight and height and age and sex:
        source = "auto"
        bmr = 10 * float(weight) + 6.25 * height - 5 * age + (5 if sex == "male" else -161)
        tdee = bmr * _ACTIVITY_COEFF.get(profile.activity_level, 1.375)
        pace = min(float(profile.pace_kg_week or 0.5), 1.0)
        protein_floor = None
        if goal == "lose":
            calories = tdee - min(pace * 1100, tdee * 0.25)
            bmi = float(weight) / ((height / 100) ** 2)
            if bmi < 18.5:
                warning = (
                    "Vazningiz me'yordan past (BMI < 18.5) — ozish tavsiya etilmaydi. "
                    "Iltimos, shifokorga murojaat qiling."
                )
        elif goal == "gain":
            calories = tdee + min(pace * 1100, tdee * 0.15)
        elif goal == "muscle":
            calories = tdee * 1.10
            protein_floor = 1.6
        else:  # condition / maintain
            calories = tdee
        floor = 1200 if sex == "female" else 1500
        calories = int(round(max(calories, floor)))
        carbs_g, protein_g, fat_g = _split_macros(calories, split, weight, protein_floor)
        explanation = _target_explanation(goal, pace, calories, tdee)
    # --- 3) Default tier ---
    else:
        source = "default"
        calories = _DEFAULT_CALORIES
        carbs_g, protein_g, fat_g = _split_macros(calories, _MACRO_SPLIT["default"])
        explanation = "Profil to'liq emas — standart 2000 kkal"

    # --- Foydalanuvchi qo'lda tahriri (override) — faqat auto/default (doctor ustun) ---
    if source != "doctor" and profile and profile.target_overrides:
        ov = profile.target_overrides
        floor = 1500 if sex == "male" else 1200
        if ov.get("calories") is not None:
            calories = max(floor, min(int(ov["calories"]), 10000))
        if ov.get("protein_g") is not None:
            protein_g = max(20, min(int(ov["protein_g"]), 500))
        if ov.get("carbs_g") is not None:
            carbs_g = max(20, min(int(ov["carbs_g"]), 800))
        if ov.get("fat_g") is not None:
            fat_g = max(15, min(int(ov["fat_g"]), 300))
        explanation = "Siz belgilagan qiymatlar"
        warning = None

    # --- Har-mahal taqsimot ---
    # Yaxlitlash qoldig'i oxirgi mahalga (yig'indi = calories aynan teng bo'lsin).
    meals = profile.meals_per_day if profile else "three"
    split = _MEAL_SPLIT.get(meals, _MEAL_SPLIT["three"])
    per_meal = []
    assigned = 0
    for idx, (mt, pct) in enumerate(split):
        if idx < len(split) - 1:
            c = round(calories * pct / 100)
            assigned += c
        else:
            c = calories - assigned  # qoldiq oxirgi mahalga
        per_meal.append({"meal_type": mt, "calories": c})

    return {
        "source": source,
        "calories": calories,
        "carbs_g": carbs_g,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "per_meal": per_meal,
        "explanation": explanation,
        "warning": warning,
    }

_MEAL_LABEL = {
    "breakfast": "nonushta",
    "lunch": "tushlik",
    "dinner": "kechki ovqat",
    "snack": "gazak",
}

def build_meal_advice(user, calories, glycemic_load, meal_type):
    """Pro: har-mahal qisqa shaxsiy tavsiya (deterministik, target/qoldiqga asoslangan).

    Insight, tashxis EMAS. Bo'sh bo'lsa None.
    """
    if not calories:
        return None
    today = date.today()
    targets = resolve_targets(user, today)
    summary = get_daily_summary(user, today)
    remaining = summary.get("calories", {}).get("remaining")
    per_meal = {m["meal_type"]: m["calories"] for m in targets["per_meal"]}
    budget = per_meal.get(meal_type)
    parts = []
    if budget and calories > budget * 1.15:
        over = int(calories - budget)
        label = _MEAL_LABEL.get(meal_type, "ovqat")
        parts.append(
            f"Bu taom ~{int(calories)} kkal — {label} byudjetingizdan {over} kkal ko'p."
        )
    if remaining is not None and remaining < 0:
        parts.append(
            f"Bugungi normadan {abs(int(remaining))} kkal oshdingiz — keyingi ovqatni yengil qiling."
        )
    if glycemic_load == "high" and _has_diabetes(user):
        parts.append("Bu taom yuqori glikemik yukka ega — qon qandingizni kuzating.")
    return " ".join(parts) or None

def has_diet_pro_feature(user, key: str) -> bool:
    """Pro flag tekshiruvi (payments sozlanmagan bo'lsa Free'ga degrade)."""
    try:
        return bool(has_pro_feature(user, key))
    except Exception:
        return False

def get_diet_progress(user, weeks: int = 4) -> dict:
    """Haftalik parhez progressi — vazn dinamikasi + o'rtacha kaloriya + streak.

    Manba: 'Vazn' HealthIndicator + diet kaloriya indikatorlari + DietProfile target.
    """
    today = date.today()
    weeks = max(1, min(weeks, 12))
    start = today - timedelta(days=weeks * 7)
    wtype = HealthIndicatorType.objects.filter(system_key="weight").first()
    profile = DietProfile.objects.filter(user=user).first()
    cal_type = get_macros_types(create_missing=False).get("calories")

    weights = (
        list(
            HealthIndicator.objects.filter(
                user=user, indicator_type=wtype, date__gte=start
            ).order_by("date")
        )
        if wtype
        else []
    )
    start_weight = float(weights[0].value) if weights else None
    current_weight = float(weights[-1].value) if weights else None
    target_weight = (
        float(profile.target_weight_kg)
        if profile and profile.target_weight_kg
        else None
    )

    weekly = []
    for w in range(weeks):
        wk_start = today - timedelta(days=(weeks - w) * 7)
        wk_end = wk_start + timedelta(days=7)
        wk_weights = [float(x.value) for x in weights if wk_start <= x.date < wk_end]
        avg_weight = round(sum(wk_weights) / len(wk_weights), 1) if wk_weights else None
        avg_calories = None
        days_logged = 0
        if cal_type:
            rows = HealthIndicator.objects.filter(
                user=user, indicator_type=cal_type, date__gte=wk_start, date__lt=wk_end
            )
            by_day = {}
            for r in rows:
                by_day[r.date] = by_day.get(r.date, 0) + int(r.value)
            days_logged = len(by_day)
            if days_logged:
                avg_calories = round(sum(by_day.values()) / days_logged)
        weekly.append(
            {
                "week_start": wk_start.isoformat(),
                "avg_weight": avg_weight,
                "avg_calories": avg_calories,
                "days_logged": days_logged,
            }
        )

    on_track = None
    if start_weight and current_weight and profile:
        if profile.goal == "lose":
            on_track = current_weight <= start_weight
        elif profile.goal in ("gain", "muscle"):
            on_track = current_weight >= start_weight
        else:
            on_track = True

    # Streak — bugundan orqaga ketma-ket log qilingan kunlar
    logged = set(
        DietEntry.objects.filter(
            user=user, date__gte=today - timedelta(days=90)
        ).values_list("date", flat=True)
    )
    streak = 0
    d = today
    while d in logged:
        streak += 1
        d -= timedelta(days=1)

    ai_summary = None
    if start_weight is not None and current_weight is not None:
        diff = round(current_weight - start_weight, 1)
        if diff < 0:
            ai_summary = f"So'nggi {weeks} haftada {abs(diff)} kg kamaydingiz — davom eting!"
        elif diff > 0:
            ai_summary = f"So'nggi {weeks} haftada {diff} kg qo'shildi."
        else:
            ai_summary = "Vazningiz barqaror."

    return {
        "start_weight": start_weight,
        "current_weight": current_weight,
        "target_weight": target_weight,
        "weekly": weekly,
        "on_track": on_track,
        "streak_days": streak,
        "ai_summary": ai_summary,
    }

def record_weight(user, kg):
    """Vazn o'zgarishini 'Vazn' (system_key='weight') HealthIndicator sifatida yozadi.
    Progress grafigi shundan quriladi. Type topilmasa jim o'tadi."""
    wtype = (
        HealthIndicatorType.objects.filter(system_key="weight").first()
    )
    if not wtype or kg is None:
        return
    HealthIndicator.objects.create(
        user=user,
        indicator_type=wtype,
        value=Decimal(str(kg)),
        source=HealthIndicator.Source.MANUAL,
        recorded_at=timezone.now(),
    )

def _target_explanation(goal, pace, calories, tdee) -> str:
    if goal == "lose":
        deficit = int(round(tdee - calories))
        return f"{pace} kg/hafta ozish uchun ~{deficit} kkal defitsit"
    if goal == "gain":
        surplus = int(round(calories - tdee))
        return f"{pace} kg/hafta vazn yig'ish uchun ~{surplus} kkal profitsit"
    if goal == "muscle":
        return "Muskul chiqarish uchun +10% kaloriya, oshgan oqsil"
    return "Vaznni saqlash uchun kunlik ehtiyoj (TDEE)"

MACROS_META = {
    # system_key: (display_name_uz, unit, icon)
    "calories": ("Kaloriya", "kcal", "🔥"),
    "carbs": ("Uglevod", "g", "🌾"),
    "protein": ("Oqsil", "g", "🥩"),
    "fat": ("Yog'", "g", "🥑"),
}

def get_macros_types(create_missing: bool = True) -> dict:
    """Kaloriya + 3 macros HealthIndicatorType'larni qaytaradi.

    `system_key` orqali topiladi (stable, tarjimaga bog'liq emas).

    `create_missing=True` (default, YOZISH oqimi) — yo'q type avtomatik yaratiladi.
    `create_missing=False` (O'QISH oqimi) — yo'q type uchun kalit qaytmaydi, DB'ga
    yozilmaydi (GET side-effect'siz). Returns: {"calories": <type>, "carbs": ...}.
    """
    result = {}
    for key, (name_uz, unit, icon) in MACROS_META.items():
        obj = HealthIndicatorType.objects.filter(system_key=key).first()
        if not obj:
            if not create_missing:
                continue
            obj = HealthIndicatorType.objects.create(
                system_key=key,
                name={"uz": name_uz, "ru": "", "cyr": ""},
                unit=unit,
                icon=icon,
            )
        result[key] = obj
    return result

def add_to_daily_indicators(
    user,
    date,
    calories: int = 0,
    carbs: int = 0,
    protein: int = 0,
    fat: int = 0,
    diet_entry_id: int | None = None,
) -> None:
    """Har taom uchun 4 ta yangi HealthIndicator event yaratadi (atomic).

    Event sourcing — har ovqat o'z qatorlari bilan saqlanadi. Kunlik jami
    `get_daily_summary` ichidagi `Sum("value")` orqali olinadi. `diet_entry_id`
    `meta` ichida saqlanadi — keyin o'chirishda shu orqali topiladi.
    """
    types = get_macros_types()
    values = {
        "calories": calories,
        "carbs": carbs,
        "protein": protein,
        "fat": fat,
    }
    recorded_at = timezone.now()
    meta = {"diet_entry_id": diet_entry_id} if diet_entry_id else {}

    with transaction.atomic():
        for key, amount in values.items():
            if amount <= 0:
                continue
            HealthIndicator.objects.create(
                user=user,
                indicator_type=types[key],
                value=Decimal(amount),
                recorded_at=recorded_at,
                source=HealthIndicator.Source.DIET_AI,
                meta=meta,
            )

def remove_diet_entry_indicators(diet_entry_id: int) -> None:
    """`DietEntry` ga bog'liq barcha HealthIndicator event'larini o'chiradi."""
    HealthIndicator.objects.filter(
        source=HealthIndicator.Source.DIET_AI,
        meta__diet_entry_id=diet_entry_id,
    ).delete()

def get_daily_summary(user, date) -> dict:
    """Bitta kun uchun 4 ta indicator summary'sini qaytaradi.

    Returns:
        {
          "calories": {"consumed", "limit", "remaining", "over_limit", "percent"},
          "carbs":   {...}, "protein": {...}, "fat": {...},
          "entries_count": int,
          "status": "on_track" | "near_limit" | "over"
        }
    """
    types = get_macros_types(create_missing=False)
    # Target — doctor > auto (profil) > default (2000). Bitta manba: resolve_targets.
    targets = resolve_targets(user, date)
    limits = {
        "calories": targets["calories"],
        "carbs": targets["carbs_g"],
        "protein": targets["protein_g"],
        "fat": targets["fat_g"],
    }

    summary = {}
    status_indicator = "on_track"
    for key in MACROS_META:
        type_obj = types.get(key)
        if type_obj is None:
            # Type hali yaratilmagan (hech qachon yozilmagan) — iste'mol 0
            total = Decimal(0)
        else:
            total = (
                HealthIndicator.objects.filter(
                    user=user, indicator_type=type_obj, date=date
                ).aggregate(total=Sum("value"))
            )["total"] or Decimal(0)
        consumed = int(total)
        limit_val = limits[key]
        remaining = None
        over_limit = False
        percent = None
        if limit_val:
            remaining = limit_val - consumed
            over_limit = consumed > limit_val
            percent = int((consumed / limit_val) * 100) if limit_val > 0 else None
            if over_limit:
                status_indicator = "over"
            elif percent is not None and percent >= 90 and status_indicator != "over":
                status_indicator = "near_limit"
        summary[key] = {
            "consumed": consumed,
            "limit": limit_val,
            "remaining": remaining,
            "over_limit": over_limit,
            "percent": percent,
        }

    summary["entries_count"] = DietEntry.objects.filter(user=user, date=date).count()
    summary["status"] = status_indicator
    summary["date"] = date.isoformat()
    summary["target_source"] = targets["source"]  # doctor | auto | default
    return summary


# Strukturali JSON kelmagan kamdan-kam holatlarda — javob ichidan
# estimated_calories'li JSON blokini topib oluvchi zaxira pattern.
