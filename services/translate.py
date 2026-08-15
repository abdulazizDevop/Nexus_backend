"""Tarjima va transliteratsiya xizmati.

Ikki xil konversiya:

1. **Transliteratsiya** (O'zbek Lotin ↔ O'zbek Kirill) — qoidalar bo'yicha,
   deterministik, oflayn. AI kerak emas.

2. **Tarjima** (O'zbek ↔ Rus) — semantik tarjima, Gemini orqali.
   Token boshiga ~$0.0001, Redis cache 24 soat saqlaydi.

Admin paneldagi "Auto-tarjima" tugmasi `auto_translate_all()` ni chaqiradi va
3 tilning hammasini qaytaradi (manba til as-is, qolgani tarjima).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Literal

from django.core.cache import cache

from services.gemini import generate_text

logger = logging.getLogger(__name__)

Lang = Literal["uz", "ru", "cyr"]

# === O'zbek Kirill ↔ Lotin transliteratsiyasi (deterministik) ===

# Tartibi muhim — uzun harflar avval (Yo, Yu, Ya, Sh, Ch va h.k.) — JSON dict
# Python 3.7+ tartibni saqlaydi.
_CYR_TO_LAT: list[tuple[str, str]] = [
    # O'zbek maxsus harflari avval (qo'shaloq belgi)
    ("Ў", "O'"), ("Қ", "Q"), ("Ғ", "G'"), ("Ҳ", "H"),
    # Ko'p harfli kirill harflar — Lotinda bir nechta harf bilan
    ("Ё", "Yo"), ("Ю", "Yu"), ("Я", "Ya"),
    ("Ш", "Sh"), ("Ч", "Ch"), ("Щ", "Sch"), ("Ц", "Ts"),
    # Bir harfli
    ("А", "A"), ("Б", "B"), ("В", "V"), ("Г", "G"), ("Д", "D"),
    ("Е", "E"), ("Ж", "J"), ("З", "Z"), ("И", "I"), ("Й", "Y"),
    ("К", "K"), ("Л", "L"), ("М", "M"), ("Н", "N"), ("О", "O"),
    ("П", "P"), ("Р", "R"), ("С", "S"), ("Т", "T"), ("У", "U"),
    ("Ф", "F"), ("Х", "X"), ("Э", "E"),
    # Yumshatuvchi/qattiqlashtiruvchi belgilar — Lotinda yo'q
    ("Ъ", "'"), ("Ы", "I"), ("Ь", ""),
]

# Aks: Lotin → Kirill (digraph va apostrofli birikmalar avval)
_LAT_TO_CYR: list[tuple[str, str]] = [
    # O'zbek maxsus — apostrof bilan
    ("O'", "Ў"), ("o'", "ў"),
    ("G'", "Ғ"), ("g'", "ғ"),
    # Digraph'lar (3 harfli avval)
    ("Sch", "Щ"), ("sch", "щ"),
    ("Yo", "Ё"), ("yo", "ё"),
    ("Yu", "Ю"), ("yu", "ю"),
    ("Ya", "Я"), ("ya", "я"),
    ("Sh", "Ш"), ("sh", "ш"),
    ("Ch", "Ч"), ("ch", "ч"),
    ("Ts", "Ц"), ("ts", "ц"),
    # Bir harfli
    ("A", "А"), ("a", "а"), ("B", "Б"), ("b", "б"),
    ("V", "В"), ("v", "в"), ("G", "Г"), ("g", "г"),
    ("D", "Д"), ("d", "д"), ("E", "Е"), ("e", "е"),
    ("J", "Ж"), ("j", "ж"), ("Z", "З"), ("z", "з"),
    ("I", "И"), ("i", "и"), ("Y", "Й"), ("y", "й"),
    ("K", "К"), ("k", "к"), ("L", "Л"), ("l", "л"),
    ("M", "М"), ("m", "м"), ("N", "Н"), ("n", "н"),
    ("O", "О"), ("o", "о"), ("P", "П"), ("p", "п"),
    ("R", "Р"), ("r", "р"), ("S", "С"), ("s", "с"),
    ("T", "Т"), ("t", "т"), ("U", "У"), ("u", "у"),
    ("F", "Ф"), ("f", "ф"), ("X", "Х"), ("x", "х"),
    ("Q", "Қ"), ("q", "қ"), ("H", "Ҳ"), ("h", "ҳ"),
    # Lotin 'c' — digraf'lardan (Ch/Ts/Sch) keyin, alohida harf sifatida 'ц'
    ("C", "Ц"), ("c", "ц"),
]


def transliterate_cyr_to_lat(text: str) -> str:
    """O'zbek Kirill → O'zbek Lotin (deterministik)."""
    if not text:
        return ""
    result = text
    for cyr, lat in _CYR_TO_LAT:
        result = result.replace(cyr, lat)
        result = result.replace(cyr.lower(), lat.lower())
    return result


def transliterate_lat_to_cyr(text: str) -> str:
    """O'zbek Lotin → O'zbek Kirill (deterministik)."""
    if not text:
        return ""
    result = text
    for lat, cyr in _LAT_TO_CYR:
        result = result.replace(lat, cyr)
    return result


# === O'zbek ↔ Rus (Gemini orqali, Redis cache) ===

_LANG_LABEL = {
    "uz": "Uzbek language using Latin alphabet (modern Uzbek)",
    "cyr": "Uzbek language using Cyrillic alphabet",
    "ru": "Russian language",
}

_TRANSLATE_PROMPT = (
    "You are a precise translator for a medical platform.\n"
    "Translate the following text from {source} to {target}.\n"
    "\n"
    "Rules:\n"
    "- Output ONLY the translated text, no quotes, no explanations, no markdown.\n"
    "- Preserve the original meaning and tone (formal/medical).\n"
    "- Keep numbers, dates, product names, ATX codes and proper nouns unchanged.\n"
    "- If the source text is already in the target language, output it as-is.\n"
    "\n"
    "Source text:\n{text}"
)

_CACHE_TTL = 60 * 60 * 24  # 24 soat
_CACHE_PREFIX = "translate:v1"


def _cache_key(text: str, source: Lang, target: Lang) -> str:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:24]
    return f"{_CACHE_PREFIX}:{source}:{target}:{digest}"


def translate_one(text: str, source: Lang, target: Lang) -> str:
    """Bir matnni `source` tilidan `target` tiliga aylantiradi.

    - O'zbek Lotin ↔ Kirill: transliteratsiya (offline, deterministik)
    - O'zbek ↔ Rus: Gemini AI
    - Source == target: matn o'zi
    """
    if not text or not text.strip():
        return ""
    if source == target:
        return text

    # O'zbek Lotin ↔ Kirill — transliteratsiya bilan tezroq va aniqroq
    if {source, target} == {"uz", "cyr"}:
        return (
            transliterate_lat_to_cyr(text) if target == "cyr"
            else transliterate_cyr_to_lat(text)
        )

    # Boshqa kombinatsiyalar — Gemini AI
    key = _cache_key(text, source, target)
    cached = cache.get(key)
    if cached:
        return cached

    prompt = _TRANSLATE_PROMPT.format(
        source=_LANG_LABEL[source],
        target=_LANG_LABEL[target],
        text=text.strip(),
    )

    result = generate_text(prompt)
    translated = (result.get("text") or "").strip()

    if not translated:
        logger.warning(
            "Gemini bo'sh tarjima qaytardi: source=%s target=%s text=%r",
            source, target, text[:80],
        )
        return ""

    cache.set(key, translated, _CACHE_TTL)
    return translated


def auto_translate_all(text: str, source: Lang) -> dict[str, str]:
    """Bir matnni 3 tilga ham aylantiradi.

    Manba til as-is, qolgan ikkitasi tarjima qilinadi. Ru ↔ Uz uchun Gemini,
    Uz ↔ Cyr uchun transliteratsiya.

    Returns:
        `{"uz": "...", "ru": "...", "cyr": "..."}`
    """
    if source not in ("uz", "ru", "cyr"):
        raise ValueError(f"Noto'g'ri source: {source!r}")

    result: dict[str, str] = {source: text}

    if source == "uz":
        result["cyr"] = transliterate_lat_to_cyr(text)
        result["ru"] = translate_one(text, "uz", "ru")
    elif source == "cyr":
        result["uz"] = transliterate_cyr_to_lat(text)
        # Ru tarjima uchun uz lotinidan boshlash sifatliroq (Gemini lotinni
        # yaxshiroq tushunadi va rus matnini standart yozadi)
        result["ru"] = translate_one(result["uz"], "uz", "ru")
    else:  # ru
        result["uz"] = translate_one(text, "ru", "uz")
        result["cyr"] = transliterate_lat_to_cyr(result["uz"])

    return result
