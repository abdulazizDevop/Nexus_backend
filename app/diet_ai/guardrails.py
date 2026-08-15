"""Xavfsizlik tekshiruvlari — xatarli savollarni AI'ga uzatmasdan bloklash.

3 qatlamli himoya:
    1. Oldindan tekshirish (bu fayl) — kalit so'zlar bo'yicha
    2. System prompt orqali AI o'zi cheklaydi (prompts.py)
    3. Keyingi tekshirish — Gemini javobida xatarli kontent bo'lsa (kelajakda)
"""

import re


# O'zbekcha + ruscha xatarli kalit so'zlar
DANGEROUS_KEYWORDS = [
    # Suitsid / o'z-o'ziga zarar
    "o'z jonim",
    "oz jonim",
    "o'z jonimni",
    "suicide",
    "suitsid",
    "o'zimni o'ldirish",
    "ozimni oldirish",
    "o'z-o'zimni",
    "самоубий",
    "суицид",
    "покончить с собой",
    "убить себя",
    "harakat qilib",
    "osilib",
    "zaharlanib",
    # Overdose / dori noto'g'ri ishlatish
    "overdose",
    "ovordoz",
    "dozadan ziyod",
    "o'ldiruvchi doza",
    "dori to'xtatib",
    "dorini tashlab",
    "doza oshirib",
    "прекратить прием",
    "не принимать",
    "прекратить принимать",
    "остановить лечение",
    # Abort / homila
    "homila tushir",
    "abort",
    "аборт",
    "homilani olib tashla",
    "прервать беременность",
    # Zaharli moddalar
    "zahar ich",
    "yadovit",
    "отравление",
    "яд выпить",
    # Kasallikka aloqador og'ir savollar
    "cancer davolash",
    "rak davolash",
    "saraton davolash",
    "рак лечить",
    "лечить рак",
]

# Tibbiy cheklovli mavzular (bloklanmaydi, lekin AI ogohlantirib yo'naltiradi)
MEDICAL_REDIRECT_KEYWORDS = [
    "dori ich",
    "dori yoz",
    "davolash",
    "diabet",
    "gipertoniya davolash",
    "лекарство",
    "назначить",
    "лечить",
]


def is_dangerous(text: str) -> tuple[bool, str]:
    """Savolda xatarli kontent bormi?

    Returns:
        (True, reason) — xatarli
        (False, "")    — xavfsiz
    """
    if not text:
        return False, ""

    lower = text.lower()

    for keyword in DANGEROUS_KEYWORDS:
        # To'liq so'z yoki ibora topilsa
        if keyword.lower() in lower:
            return True, "Xavfli mavzu aniqlandi"

    # Qo'shimcha regex tekshiruvi: "o'zimni ... o'ldir"
    patterns = [
        r"o'?zi?mni.*o'?ldir",
        r"убить?\s+(себя|меня)",
        r"хочу\s+умер",
    ]
    for pat in patterns:
        if re.search(pat, lower):
            return True, "Xavfli niyat aniqlandi"

    return False, ""


def get_safety_response(language: str = "uz") -> str:
    """Xatarli savol uchun javob."""
    responses = {
        "uz": (
            "⚠️ Bu savol parhez mavzusidan tashqarida yoki jiddiy tibbiy "
            "aralashuv talab qiladi.\n\n"
            "**Iltimos, darhol shifokoringizga yoki ishonchli yaqiningizga murojaat qiling.**\n\n"
            "Agar sizda ruhiy holat yoki jonga xavf bor bo'lsa — **1122** (Aloqa markazi) "
            "yoki tez tibbiy yordam **103**.\n\n"
            "Men faqat oddiy parhez va ovqatlanish bo'yicha maslahat bera olaman."
        ),
        "uz-cyrl": (
            "⚠️ Бу савол парҳез мавзусидан ташқарида ёки жиддий тиббий "
            "аралашув талаб қилади.\n\n"
            "**Илтимос, дарҳол шифокорингизга ёки ишончли яқинингизга мурожаат қилинг.**\n\n"
            "Агар сизда руҳий ҳолат ёки жонга хавф бор бўлса — **1122** "
            "ёки тез тиббий ёрдам **103**."
        ),
        "ru": (
            "⚠️ Этот вопрос выходит за рамки диеты или требует серьёзного "
            "медицинского вмешательства.\n\n"
            "**Пожалуйста, немедленно обратитесь к врачу или близкому человеку.**\n\n"
            "Если есть угроза жизни — позвоните **1122** (Центр помощи) или "
            "скорую помощь **103**.\n\n"
            "Я могу помочь только с общими вопросами диеты и питания."
        ),
    }
    if language == "cyr":  # cyr → kirill (aks holda uz lotinga tushardi)
        language = "uz-cyrl"
    return responses.get(language, responses["uz"])
