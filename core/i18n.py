"""Til (i18n) yordamchilari.

Mediik 3 tilni qo'llab-quvvatlaydi: O'zbek Lotin (`uz`), Rus (`ru`),
O'zbek Kirill (`cyr`). Backend ma'lumotni JSON field'larda saqlaydi (
masalan, `Specialty.name = {"uz": "Kardiolog", "ru": "Кардиолог", "cyr":
"Кардиолог"}`). API'dagi `?lang=` query, `X-Language` header yoki
`Accept-Language` header'iga qarab mos qiymat qaytariladi.
"""

from __future__ import annotations

from typing import Mapping, Optional

SUPPORTED_LANGS: tuple[str, ...] = ("uz", "ru", "cyr")
DEFAULT_LANG: str = "uz"


def get_request_lang(request) -> str:
    """Hozirgi so'rov uchun tilni aniqlaydi.

    Priority:
      1. `?lang=<code>` query param
      2. `X-Language: <code>` header (admin/web tomondan oson set qilinadi)
      3. `Accept-Language` standart header (mobile va brauzerlar yuboradi)
      4. `request.user.settings.language` (autentifikatsiyalangan user uchun)
      5. `DEFAULT_LANG` ("uz")
    """
    if request is None:
        return DEFAULT_LANG

    # 1) Explicit query param
    query_lang = (request.GET.get("lang") or "").lower() if hasattr(request, "GET") else ""
    if query_lang in SUPPORTED_LANGS:
        return query_lang

    # 2) POST/PATCH body (form-data uchun) — request.data malformed body'da
    # DRF ParseError chiqarishi mumkin, til qidirishimiz uni partlatmasin.
    if hasattr(request, "data"):
        try:
            body_lang = (request.data.get("lang") or "").lower()
        except Exception:
            body_lang = ""
        if body_lang in SUPPORTED_LANGS:
            return body_lang

    # 2) Custom header
    headers = getattr(request, "headers", {}) or {}
    custom = (headers.get("X-Language") or headers.get("X-LANGUAGE") or "").lower()
    if custom in SUPPORTED_LANGS:
        return custom

    # 3) Accept-Language
    accept = (headers.get("Accept-Language") or "").lower()
    for chunk in accept.split(","):
        code = chunk.strip().split(";")[0].split("-")[0]
        if code in SUPPORTED_LANGS:
            return code
        # uz-Cyrl yoki uz-Latn uchun ham
        if code == "uz":
            return "uz"

    # 4) User preference
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        try:
            pref = (getattr(user.settings, "language", "") or "").lower()
            if pref in SUPPORTED_LANGS:
                return pref
        except Exception:
            pass

    return DEFAULT_LANG


def pick_translation(
    raw,
    lang: str,
    fallback: str = DEFAULT_LANG,
):
    """JSON translation dict'idan tilga mos qiymat tanlaydi.

    Qiymat string yoki list bo'lishi mumkin:
    - `{"uz": "Kardiolog"}` → "Kardiolog" (string)
    - `{"uz": ["chat", "voice"]}` → ["chat", "voice"] (list)

    Mantiq:
    - `raw` string bo'lsa — to'g'ridan-to'g'ri qaytaradi (eski format).
    - `raw` dict bo'lsa — `lang` → `fallback` → birinchi non-empty qiymat.
    - `raw` bo'sh/None bo'lsa — bo'sh string (string nomzod) yoki bo'sh ro'yxat
      ([]) qaytariladi (qiymatga qarab).
    """
    if raw == []:
        # Bo'sh RO'YXAT — qiymat tipi (masalan "features"), shundayligicha qoladi.
        return []
    if raw is None or raw == "" or raw == {}:
        # Bo'sh dict — bu tarjima KONTEYNERI, qiymat emas. Avval xom `{}`
        # qaytarilardi: mijoz bir yozuvda string, boshqasida obyekt olib
        # tiplar chalkashardi (React #31 / mobil parse xatosi).
        return ""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, Mapping):
        return ""

    value = raw.get(lang)
    if value:
        return value
    value = raw.get(fallback)
    if value:
        return value
    # Birinchi non-empty qiymat
    for v in raw.values():
        if v:
            return v
    # Hammasi bo'sh — birinchi mavjud (tip saqlash uchun)
    for v in raw.values():
        return v
    return ""


def pick_for(context, raw, fallback: str = DEFAULT_LANG):
    """Serializer context'idan tilni olib `pick_translation` chaqiradi.

    Lang qiymati `context["_resolved_lang"]` ostida cache'lanadi — katta
    listda (~50 obj × 3 field) header parsing 150 marta emas, 1 marta
    bajariladi.
    """
    if context is None:
        return pick_translation(raw, DEFAULT_LANG, fallback)
    lang = context.get("_resolved_lang")
    if not lang:
        lang = get_request_lang(context.get("request"))
        context["_resolved_lang"] = lang
    return pick_translation(raw, lang, fallback)


def normalize_translations(
    raw,
    source: Optional[str] = None,
):
    """Har qanday kelgan qiymatni `{uz, ru, cyr}` lug'atiga normalize qiladi.

    String yoki list qiymatlar uchun ishlaydi:
    - String `"Kardiolog"` → `{"uz": "Kardiolog", "ru": "", "cyr": ""}`
    - List `["chat"]` → `{"uz": ["chat"], "ru": [], "cyr": []}`
    - Dict — qo'llab-quvvatlanmagan kalitlar olib tashlanadi, default qiymatlar
      to'ldiriladi.
    """
    # Default'lar — qiymat turiga qarab string yoki list
    if raw is None:
        return {lang: "" for lang in SUPPORTED_LANGS}

    if isinstance(raw, str):
        out = {lang: "" for lang in SUPPORTED_LANGS}
        out[source or DEFAULT_LANG] = raw
        return out

    if isinstance(raw, list):
        out = {lang: [] for lang in SUPPORTED_LANGS}
        out[source or DEFAULT_LANG] = list(raw)
        return out

    if isinstance(raw, Mapping):
        # Tipni dict ichidagi birinchi qiymatdan aniqlash
        any_value = next((v for v in raw.values() if v is not None), None)
        is_list_field = isinstance(any_value, list)
        empty = [] if is_list_field else ""
        out = {lang: empty for lang in SUPPORTED_LANGS}
        for lang in SUPPORTED_LANGS:
            value = raw.get(lang)
            if value is not None:
                # List field uchun — listni saqlaymiz; string uchun stringni
                if is_list_field and isinstance(value, list):
                    out[lang] = list(value)
                elif not is_list_field and isinstance(value, str):
                    out[lang] = value
        return out

    return {lang: "" for lang in SUPPORTED_LANGS}
