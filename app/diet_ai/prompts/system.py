from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar
from .rules import get_base_rules

DIET_CHAT_LANG_DIRECTIVE = (
    "MUHIM — JAVOB TILI: foydalanuvchi qaysi tilda yozsa, AYNAN o'sha tilda javob ber "
    "(ruscha → ruscha, o'zbek lotin → o'zbek lotin, o'zbek kirill → o'zbek kirill). "
    "Har xabarda foydalanuvchining oxirgi xabari tiliga moslash."
)

def _diet_fixed_directive(language: str) -> str:
    """Rasm tahlili uchun — qat'iy til (mirror qiladigan foydalanuvchi matni yo'q)."""
    if language == "ru":
        return "ВАЖНО: отвечайте СТРОГО и ТОЛЬКО на русском языке."
    if language in ("cyr", "uz-cyrl"):
        return "МУҲИМ: фақат ЎЗБЕК (КИРИЛЛ) тилида жавоб беринг."
    return "MUHIM: faqat O'ZBEK (lotin) tilida javob bering."

def build_system_prompt(language: str, user_context: str, mirror: bool = True) -> str:
    """Base qoidalar + user context.

    mirror=True (chat) — model foydalanuvchi yozgan tilga moslashadi.
    mirror=False (rasm tahlili) — qat'iy `language` (app tili) — rasmda mirror
    qiladigan matn yo'q, shuning uchun app tilini majburlaymiz.
    """
    rules = get_base_rules(language)
    directive = DIET_CHAT_LANG_DIRECTIVE if mirror else _diet_fixed_directive(language)
    return f"{directive}\n\n{rules}\n\n---\n\nBEMOR MA'LUMOTLARI:\n{user_context}"
