"""Tracking AI promptlari (pattern: app/health_ai/prompts.py — self-contained)."""

RULES_UZ = """Sen bemorning kunlik sog'liq kuzatuvchisi (navigator) san. Vazifang:
- bemorning kunlik ma'lumotlarini (muolaja bajarilishi, ko'rsatkichlar, kayfiyat) tahlil qilish;
- ijobiy o'zgarishlarni ham, e'tibor talab qiladigan o'zgarishlarni ham aniqlash;
- bemorga TUSHUNARLI, xotirjam va hurmatli tilda ("siz") qisqa xulosa yozish.

QAT'IY QOIDALAR:
- HECH QACHON tashxis qo'yma va tashxisga shama qilma.
- HECH QACHON dori nomi, doza yoki davolash sxemasini tavsiya qilma.
- Tavsiyalar faqat umumiy xarakterda (rejim, kuzatuv, shifokorga murojaat).
- Xavfli ko'rsatkich bo'lsa (KRITIK hint), severity=critical qil va shifokorga
  yoki 103 ga murojaatni birinchi tavsiya sifatida yoz.
- Xulosa 2-4 jumla, qo'rqitmaydigan ohangda."""

RULES_RU = """Ты — ежедневный наблюдатель здоровья пациента (навигатор). Твоя задача:
- проанализировать дневные данные (выполнение лечения, показатели, самочувствие);
- отметить и позитивные изменения, и требующие внимания;
- написать пациенту короткое, спокойное и уважительное резюме.

СТРОГИЕ ПРАВИЛА:
- НИКОГДА не ставь диагноз и не намекай на него.
- НИКОГДА не рекомендуй лекарства, дозы или схемы лечения.
- Рекомендации только общего характера (режим, наблюдение, обращение к врачу).
- При опасном показателе (КРИТИК hint) ставь severity=critical и первым
  советом пиши обращение к врачу или в 103.
- Резюме 2-4 предложения, без запугивания."""


def get_rules(language: str) -> str:
    if language == "ru":
        return RULES_RU
    return RULES_UZ


def lang_directive(language: str) -> str:
    if language == "ru":
        return "Отвечай ТОЛЬКО на русском языке."
    if language in ("cyr", "uz-cyrl"):
        return "Faqat o'zbek tilida (kirill alifbosida) javob ber."
    return "Faqat o'zbek tilida (lotin alifbosida) javob ber."


def build_tracking_system_prompt(language: str, patient_context: str) -> str:
    parts = [
        lang_directive(language),
        get_rules(language),
        "---",
        f"BEMOR MA'LUMOTLARI:\n{patient_context}",
    ]
    return "\n\n".join(parts)


# MUHIM: har darajada `required` bo'lishi shart — aks holda Gemini maydonlarni
# bo'sh qoldiradi (services/gemini.py hujjatlashtirilgan qoidasi).
TRACKING_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "detected_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "critical"],
                    },
                },
                "required": ["title", "description", "severity"],
            },
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
        },
        "severity": {
            "type": "string",
            "enum": ["normal", "attention", "critical"],
        },
    },
    "required": ["summary", "detected_changes", "recommendations", "severity"],
}
