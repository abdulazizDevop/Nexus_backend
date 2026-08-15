"""Geokodlash — OpenStreetMap Nominatim (API kaliti kerak emas).

Nima uchun backend orqali (brauzerdan to'g'ridan-to'g'ri emas):
  1. Nominatim ishlatish shartlari aniq `User-Agent` talab qiladi — brauzer uni
     o'rnata olmaydi va so'rovlar bloklanishi mumkin.
  2. Javob cache'lanadi: bir xil nuqta uchun qayta so'rov ketmaydi
     (siyosat: sekundiga 1 so'rovdan ko'p emas).
  3. CORS muammosi bo'lmaydi.

Manzil MATNI tozalanadi: pochta indeksi, mamlakat va "Tuman/Viloyat" kabi
takroriy bo'laklar tashlab yuboriladi — foydalanuvchiga qisqa, o'qiladigan
manzil qoladi.
"""

import logging

import httpx
from django.core.cache import cache

logger = logging.getLogger("mediik.geocode")

_BASE = "https://nominatim.openstreetmap.org"
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)
_CACHE_TTL = 60 * 60 * 24  # 1 kun — manzil tez-tez o'zgarmaydi

# Nominatim siyosati: haqiqiy ilova nomi va aloqa manzili ko'rsatilishi shart.
_HEADERS = {"User-Agent": "Mediik/1.0 (clinic panel; https://mediik.uz)"}

# Javobdagi keraksiz bo'laklar — manzil satrida ko'rinmasin.
_SKIP_KEYS = {
    "country", "country_code", "postcode", "ISO3166-2-lvl4",
    "region", "state_district",
}


def _clean_address(data: dict) -> str:
    """Nominatim `address` lug'atidan qisqa, o'qiladigan satr yig'adi.

    Tartib: ko'cha+uy -> mahalla/tuman -> shahar. Takrorlar tashlanadi
    (Nominatim ba'zan bir nomni ikki kalitda qaytaradi).
    """
    addr = data.get("address") or {}
    house = (addr.get("house_number") or "").strip()
    road = (addr.get("road") or addr.get("pedestrian") or "").strip()

    parts = []
    if road:
        parts.append(f"{road} {house}".strip())
    for key in ("neighbourhood", "suburb", "city_district", "county"):
        value = (addr.get(key) or "").strip()
        if value:
            parts.append(value)
            break
    for key in ("city", "town", "village", "state"):
        value = (addr.get(key) or "").strip()
        if value:
            parts.append(value)
            break

    seen, out = set(), []
    for p in parts:
        low = p.lower()
        if low and low not in seen:
            seen.add(low)
            out.append(p)
    if out:
        return ", ".join(out)
    # Bo'laklar bo'sh bo'lsa — to'liq nomdan mamlakat/indeksni kesib olamiz
    display = (data.get("display_name") or "").split(",")
    keep = [x.strip() for x in display if x.strip() and not x.strip().isdigit()]
    return ", ".join(keep[:3])


def reverse(lat, lng, lang: str = "uz") -> dict:
    """Koordinata -> manzil. Xato bo'lsa `{"error": ...}` qaytadi (partlamaydi)."""
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return {"error": "invalid_coords"}

    # Cache kaliti 5 xonagacha yaxlitlanadi (~1 metr) — bir joyni bosaverganda
    # har safar tashqi so'rov ketmasin.
    key = f"geocode:rev:{lang}:{lat_f:.5f}:{lng_f:.5f}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        resp = httpx.get(
            f"{_BASE}/reverse",
            params={
                "lat": lat_f, "lon": lng_f, "format": "jsonv2",
                "zoom": 18, "addressdetails": 1, "accept-language": lang,
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Nominatim reverse xato: %s", exc)
        return {"error": "geocode_unavailable"}

    result = {
        "address": _clean_address(data),
        "display_name": data.get("display_name") or "",
        "lat": lat_f,
        "lng": lng_f,
    }
    cache.set(key, result, _CACHE_TTL)
    return result


def search(query: str, lang: str = "uz", limit: int = 5) -> list:
    """Manzil matni -> nomzod nuqtalar (xaritani o'sha joyga olib borish uchun)."""
    query = (query or "").strip()
    if len(query) < 3:
        return []

    key = f"geocode:search:{lang}:{query.lower()[:80]}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        resp = httpx.get(
            f"{_BASE}/search",
            params={
                "q": query, "format": "jsonv2", "addressdetails": 1,
                "limit": limit, "accept-language": lang,
                # O'zbekiston bilan cheklaymiz — klinika chet elda bo'lmaydi
                "countrycodes": "uz",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json() or []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Nominatim search xato: %s", exc)
        return []

    out = [
        {
            "address": _clean_address(row),
            "display_name": row.get("display_name") or "",
            "lat": float(row["lat"]),
            "lng": float(row["lon"]),
        }
        for row in rows
        if row.get("lat") and row.get("lon")
    ]
    cache.set(key, out, _CACHE_TTL)
    return out
