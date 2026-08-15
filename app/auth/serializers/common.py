from rest_framework import serializers

from django.contrib.auth import get_user_model


User = get_user_model()


def normalize_phone(value: str) -> str:
    """Telefon raqamni standart formatga keltiradi: faqat raqamlar, 998 prefiksi.

    Misollar:
        "+998 90 123 45 67" → "998901234567"
        "+998-90-123-45-67" → "998901234567"
        "(99890)1234567"    → "998901234567"
        "8901234567"        → "998901234567"  (O'zbekiston ichida 8 → 998)
        "998901234567"      → "998901234567"  (allaqachon to'g'ri)

    Bot va serializer bir xil normalizatsiyani ishlatadi — bir xil raqam
    register/login/bot orqali kelganda DB'da bitta yozuv bo'lishi uchun.
    """
    if not value:
        return ""
    cleaned = (
        value.replace("+", "").replace(" ", "")
        .replace("-", "").replace("(", "").replace(")", "")
    )
    if cleaned.startswith("998"):
        return cleaned
    if cleaned.startswith("8") and len(cleaned) == 12:
        # O'zbekiston: 8 prefiksli (eski format) → 998 ga konvertatsiya
        return "998" + cleaned[1:]
    return cleaned


def validate_uz_phone(value: str) -> str:
    """Normalizatsiya + O'zbekiston raqami formatini tekshirish.

    Yaroqsiz qiymatlar (harf, noto'g'ri uzunlik, 998'siz prefiks) DB'ga axlat
    yozilishi va yaroqsiz raqamlarga SMS yuborilishining (Eskiz xarajati) oldini
    oladi. Format: 998 + 9 raqam = 12 ta raqam.
    """
    cleaned = normalize_phone(value)
    if not (cleaned.isdigit() and len(cleaned) == 12 and cleaned.startswith("998")):
        raise serializers.ValidationError(
            "Telefon raqam noto'g'ri. Format: 998XXXXXXXXX."
        )
    return cleaned
