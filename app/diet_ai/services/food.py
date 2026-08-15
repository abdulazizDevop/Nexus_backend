from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

_FOOD_DATA_BACKUP_PATTERN = re.compile(r"(\{[^{}]*\"estimated_calories\"[^{}]*\})")

def _extract_food_data(raw_fd: dict) -> dict:
    """Xom food_data dict'idan ishonchli (musbat) maydonlarni ajratib oladi."""
    food_data: dict = {}
    if not isinstance(raw_fd, dict):
        return food_data
    name = (raw_fd.get("food_name") or "").strip()
    cals = raw_fd.get("estimated_calories")
    # regression-log'idagi false-positive'ni ham yo'qotadi (0-kkal != schema buzilishi).
    if name and isinstance(cals, (int, float)) and cals >= 0:
        food_data["food_name"] = name
        food_data["estimated_calories"] = int(cals)
        grams = raw_fd.get("portion_grams")
        if isinstance(grams, (int, float)) and grams > 0:
            food_data["portion_grams"] = int(grams)
        for key in ("carbs_grams", "protein_grams", "fat_grams"):
            v = raw_fd.get(key)
            if isinstance(v, (int, float)) and v >= 0:
                food_data[key] = int(v)
        gl = raw_fd.get("glycemic_load")
        if gl in ("low", "medium", "high"):
            food_data["glycemic_load"] = gl
        ingredients = _sanitize_ingredients(raw_fd.get("ingredients"))
        if ingredients:
            food_data["ingredients"] = ingredients
    return food_data

def _sanitize_ingredients(raw) -> list:
    """AI ingredient ro'yxatini tozalaydi — har biri {name, grams, macro}.

    Noto'g'ri/bo'sh elementlarni tashlaydi. Musbat bo'lmagan qiymatlar 0 ga tushadi.
    """
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name[:120]}
        for key in ("grams", "calories", "carbs_g", "protein_g", "fat_g"):
            v = item.get(key)
            row[key] = int(v) if isinstance(v, (int, float)) and v >= 0 else 0
        cleaned.append(row)
    return cleaned

def parse_food_analysis_response(ai_raw_text: str) -> tuple[str, dict, bool]:
    """Gemini structured-JSON javobini parse qiladi.

    Returns:
        (clean_text, food_data, food_detected)
        - clean_text: foydalanuvchiga ko'rsatiladigan markdown matn
        - food_data: {food_name, estimated_calories, portion_grams, *_grams}
        - food_detected: rasmda ovqat topilganmi

    FOOD_ANALYSIS_SCHEMA bilan struktural JSON qaytadi. Kamdan-kam holatda
    (schema ishlamasa) javob ichidagi JSON blok zaxira pattern bilan olinadi.
    """
    ai_raw_text = ai_raw_text or ""
    clean_text = ai_raw_text
    food_data: dict = {}
    food_detected = True  # Fallback default

    try:
        parsed = json.loads(ai_raw_text)
    except (ValueError, json.JSONDecodeError):
        parsed = None

    if isinstance(parsed, dict):
        clean_text = (parsed.get("analysis_markdown") or "").strip()
        food_detected = bool(parsed.get("food_detected", True))
        if food_detected:
            food_data = _extract_food_data(parsed.get("food_data") or {})
    else:
        # Zaxira: javob ichidan JSON blokni qidirish (marker yo'q)
        match = _FOOD_DATA_BACKUP_PATTERN.search(ai_raw_text)
        if match:
            try:
                food_data = _extract_food_data(json.loads(match.group(1)))
            except (ValueError, json.JSONDecodeError):
                food_data = {}

    return clean_text, food_data, food_detected


# ── Ingredient qayta hisoblash (B6.3) ──────────────────────────────────────
# Foydalanuvchi taom ingredientlarini tahrirlaydi (gramm o'zgartiradi, o'chiradi,
# yangi qo'shadi). Qoidalar:
#   1. Mavjud ingredient, gramm o'zgardi  → chiziqli scale (AI'ga murojaat YO'Q).
#   2. Ingredient o'chirildi                → yig'indidan tushib qoladi.
#   3. Yangi ingredient                     → per-100g AI mini-call, so'ng gramm'ga scale.
#   4. Entry jami = ingredientlar yig'indisi (qayta yoziladi).
# glycemic_load va meal_advice QAYTA hisoblanmaydi.

_INGREDIENT_100G_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "calories": {"type": "integer"},
        "carbs_g": {"type": "integer"},
        "protein_g": {"type": "integer"},
        "fat_g": {"type": "integer"},
    },
    "required": ["found", "calories", "carbs_g", "protein_g", "fat_g"],
}

_INGREDIENT_KEYS = ("calories", "carbs_g", "protein_g", "fat_g")

class UnknownIngredient(Exception):
    """Yangi ingredient uchun ozuqaviy qiymat topilmadi (AI tanimadi)."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(name)

def estimate_ingredient_per100g(name: str) -> dict | None:
    """Noma'lum ingredientning 100g ozuqaviy qiymati (Gemini mini-call).

    Returns {calories, carbs_g, protein_g, fat_g} yoki topilmasa None.
    """
    from services.gemini import generate_text

    prompt = (
        f"'{name}' oziq-ovqat mahsulotining 100 grammidagi taxminiy ozuqaviy qiymati. "
        "Bu tanish oziq-ovqat bo'lsa found=true qil va kaloriya (kcal) hamda "
        "makronutrientlarni (uglevod/oqsil/yog', gramm) ber. Agar bu oziq-ovqat "
        "emas yoki noma'lum bo'lsa found=false qil."
    )
    res = generate_text(
        prompt=prompt,
        response_schema=_INGREDIENT_100G_SCHEMA,
        temperature=0.1,
        max_tokens=256,
    )
    if not res or res.get("error"):
        return None
    try:
        data = json.loads(res["text"])
    except (ValueError, TypeError, KeyError):
        return None
    if not data.get("found"):
        return None
    return {k: max(0, int(data.get(k) or 0)) for k in _INGREDIENT_KEYS}

def _scale_value(value, grams_new: int, grams_orig: int) -> int:
    """Chiziqli scale: value × grams_new / grams_orig (orig 0 bo'lsa 0)."""
    if not grams_orig:
        return 0
    return max(0, round((value or 0) * grams_new / grams_orig))

def recalc_ingredients(entry, new_list: list) -> tuple[list, dict]:
    """Tahrirlangan ingredient ro'yxatidan yangi ingredientlar + entry jami.

    Args:
        entry: DietEntry (eski `ingredients` snapshot manbasi).
        new_list: [{name, grams}, ...] — mobil yuborgan tahrirlangan ro'yxat.

    Returns:
        (ingredients, totals) — ingredients har biri to'liq ozuqaviy qiymat bilan;
        totals = {calories, carbs_grams, protein_grams, fat_grams}.

    Raises:
        UnknownIngredient — yangi ingredient uchun AI qiymat topa olmasa.
    """
    orig_by_name = {}
    for i in (entry.ingredients or []):
        if isinstance(i, dict) and i.get("name"):
            orig_by_name[str(i["name"]).strip().lower()] = i

    result = []
    for item in new_list:
        name = str((item or {}).get("name", "")).strip()
        try:
            grams = int((item or {}).get("grams") or 0)
        except (TypeError, ValueError):
            grams = 0
        if not name or grams <= 0:
            continue

        orig = orig_by_name.get(name.lower())
        if orig:
            # Mavjud ingredient — chiziqli scale (deterministik).
            g0 = int(orig.get("grams") or 0)
            result.append({
                "name": name,
                "grams": grams,
                **{k: _scale_value(orig.get(k), grams, g0) for k in _INGREDIENT_KEYS},
            })
        else:
            # Yangi ingredient — per-100g AI qiymat → gramm'ga scale.
            per100 = estimate_ingredient_per100g(name)
            if not per100:
                raise UnknownIngredient(name)
            factor = grams / 100.0
            result.append({
                "name": name,
                "grams": grams,
                **{k: max(0, round(per100[k] * factor)) for k in _INGREDIENT_KEYS},
            })

    totals = {
        "calories": sum(i["calories"] for i in result),
        "carbs_grams": sum(i["carbs_g"] for i in result),
        "protein_grams": sum(i["protein_g"] for i in result),
        "fat_grams": sum(i["fat_g"] for i in result),
    }
    return result, totals
