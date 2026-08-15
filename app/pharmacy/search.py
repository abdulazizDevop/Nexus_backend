"""Pharmacy search normalizer — Kirill ↔ Lotin.

Dorilar ro'yxatida `name` Kirill va Lotin yonma-yon yoziladi:
    "Баконил™ TTS10 (Bakonil TTS10)"
Foydalanuvchi "Bakonil" yoki "Баконил" qidirsa, ikkalasi ham mos kelishi kerak.

Yechim: matnni Lotin-lowercase formatga keltirib (alfavit va o'zbek kirill tarjima
qilinadi), `name_normalized` ustunda saqlash. Search query'ni ham normalize qilib
`__icontains` qilamiz.
"""

# Asosiy ruschadan lotinga + o'zbekcha kirill harflar.
# Mediik kontekstida ilmiy yoki tarixiy transliteratsiya emas — search uchun
# bir-biriga moslashtirish maqsadi (foydalanuvchi nima yozsa ham bitta natija
# chiqsin).
CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
    # O'zbek kirill maxsus harflari
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}

# Search'ga ta'sir qiladigan belgi/simvollar — probelga almashtiriladi
SEARCH_NOISE = "™®©'`-()[]{}.,/\\|;:!?\"*&%$#@<>=+~"


def normalize_for_search(text: str) -> str:
    """Matnni Lotin-lowercase kanonik formatga keltiradi.

    Misol:
        "Баконил™ TTS10 (Bakonil TTS10)" → "bakonil tts10 bakonil tts10"
        "5-ФТОРУРАЦИЛ-ЭБЕВЕ®"             → "5 ftoruratsil ebeve"
    """
    if not text:
        return ""

    text = text.casefold()

    # Lotin yoki Kirill — birga keltiramiz
    out_chars = []
    for ch in text:
        if ch in CYRILLIC_TO_LATIN:
            out_chars.append(CYRILLIC_TO_LATIN[ch])
        elif ch.isalnum() or ch.isspace():
            out_chars.append(ch)
        else:
            out_chars.append(" ")  # apostrof, tire va h.k. probelga
    text = "".join(out_chars)

    # Ko'p probellarni bittaga
    return " ".join(text.split())
