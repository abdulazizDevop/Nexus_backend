"""Navigator AI qatlami — Gemini chaqiruvlari (kontrakt §2, §4, §7, §8).

QAT'IY QOIDALAR (keys §9):
- AI TASHXIS QO'YMAYDI — tashxis tayyor holda keladi, AI faqat yo'l quradi.
- Manual tashxisda AI DORI O'YLAB TOPMAYDI — medication qadam faqat hujjatda
  yozilgan dorilardan (from-image) yaratiladi.
- AI kontekstiga bemor ismi/telefoni UZATILMAYDI (§11) — faqat yosh, jins,
  tibbiy ma'lumot.
"""

import json
import logging

from services.gemini import generate_text, generate_with_image

logger = logging.getLogger("mediik.navigator")

# --- Umumiy: qadam (flat maydonlar — payload'ni backend yig'adi) ---
_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "order": {"type": "integer"},
        "type": {
            "type": "string",
            "enum": ["medication", "analysis", "consultation", "lifestyle", "checkup", "education"],
        },
        "title": {"type": "string"},
        "description": {"type": "string"},
        "body": {"type": "string", "description": "Faqat education uchun to'liq matn, aks holda bo'sh"},
        "due_in_days": {"type": "integer", "description": "Muddat (kun), 0 = muddatsiz"},
        "medication_name": {"type": "string", "description": "Faqat medication turi, hujjatdagi nom"},
        "dosage": {"type": "string"},
        "times_per_day": {"type": "integer"},
        "daily_times": {
            "type": "array", "items": {"type": "integer"},
            "description": "Kun boshidan daqiqalarda (480 = 08:00)",
        },
        "duration_days": {"type": "integer"},
        "notes": {"type": "string"},
        "analysis_type": {"type": "string", "description": "Faqat analysis turi (masalan blood_general)"},
        "preparation": {"type": "string"},
        "specialty": {"type": "string", "description": "Faqat consultation/checkup turi (kichik harfda)"},
        "reason": {"type": "string"},
    },
    "required": [
        "order", "type", "title", "description", "body", "due_in_days",
        "medication_name", "dosage", "times_per_day", "daily_times",
        "duration_days", "notes", "analysis_type", "preparation",
        "specialty", "reason",
    ],
}

_RED_FLAG_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "action": {"type": "string"},
        "severity": {"type": "string", "enum": ["emergency", "urgent", "watch"]},
    },
    "required": ["text", "action", "severity"],
}

_ROADMAP_FIELDS = {
    "plain_explanation": {"type": "string"},
    "what_to_watch": {"type": "array", "items": {"type": "string"}},
    "red_flags": {"type": "array", "items": _RED_FLAG_SCHEMA},
    "steps": {"type": "array", "items": _STEP_SCHEMA},
}

ROADMAP_SCHEMA = {
    "type": "object",
    "properties": dict(_ROADMAP_FIELDS),
    "required": ["plain_explanation", "what_to_watch", "red_flags", "steps"],
}

FROM_IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_medical_document": {"type": "boolean"},
        "confidence": {"type": "number", "description": "0..1 — o'qish ishonchliligi"},
        "recognized_text": {"type": "string"},
        "diagnosis_title": {"type": "string"},
        "icd10": {"type": "string", "description": "Hujjatda yozilgan bo'lsa, aks holda bo'sh"},
        "needs_review": {"type": "boolean"},
        **_ROADMAP_FIELDS,
    },
    "required": [
        "is_medical_document", "confidence", "recognized_text",
        "diagnosis_title", "icd10", "needs_review",
        "plain_explanation", "what_to_watch", "red_flags", "steps",
    ],
}

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "urgency": {
            "type": "string",
            "enum": ["emergency", "urgent", "routine", "self_care"],
        },
        "summary": {"type": "string"},
        "advice": {"type": "array", "items": {"type": "string"}},
        "recommended_specialties": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "label": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["code", "label", "reason"],
            },
        },
        "disclaimer": {"type": "string"},
    },
    "required": ["urgency", "summary", "advice", "recommended_specialties", "disclaimer"],
}

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "related_step_ids": {"type": "array", "items": {"type": "integer"}},
        "needs_doctor": {"type": "boolean", "description": "Savol shifokor konsultatsiyasini talab qiladimi"},
        "disclaimer": {"type": "string", "description": "Kerak bo'lsa disclaimer, aks holda bo'sh"},
    },
    "required": ["reply", "related_step_ids", "needs_doctor", "disclaimer"],
}


_ROADMAP_RULES = """QOIDALAR:
- Sen TASHXIS QO'YMAYSAN — tashxis allaqachon aniqlangan, sen faqat undan
  KEYINGI harakatlar yo'l xaritasini tuzasan.
- 5-8 qadam, `order` 1'dan ketma-ket. Birinchi qadam — education (kasallik
  haqida tushuncha, `body`da 3-5 jumlalik tushunarli matn).
- {med_rule}
- analysis/consultation/checkup qadamlarida shifokor yo'llanmasi nazarda
  tutilishini description'da ayt.
- red_flags — shu tashxis uchun HAQIQIY xavfli belgilar (2-4 ta), action'da
  103/tez yordam yoki shifokor.
- plain_explanation — 2-4 jumla, xotirjam, qo'rqitmaydigan ohang, "siz"da.
- Hamma matn bemorga tushunarli oddiy tilda."""

_MED_RULE_FROM_DOC = (
    "medication qadamlar FAQAT hujjatda aniq yozilgan dorilardan — nom/doza/"
    "tartibni hujjatdan ko'chir, O'ZINGDAN QO'SHMA. O'qib bo'lmaganini tashlab ket."
)
_MED_RULE_NO_MEDS = (
    "medication qadam YARATMA — dori tayinlash shifokor ishi. Buning o'rniga "
    "consultation qadamida shifokor dori rejasini tuzishini ayt."
)


def _lang_directive(language: str) -> str:
    if language == "ru":
        return "Отвечай ТОЛЬКО на русском языке."
    if language in ("cyr", "uz-cyrl"):
        return "Faqat o'zbek tilida (kirill alifbosida) javob ber."
    return "Faqat o'zbek tilida (lotin alifbosida) javob ber."


def _parse(result: dict, required_key: str):
    """Gemini natijasini dict'ga aylantiradi yoki None."""
    if "error" in result:
        return None
    try:
        parsed = json.loads(result.get("text") or "")
    except (ValueError, TypeError):
        logger.warning("Navigator AI javobi JSON emas")
        return None
    if not isinstance(parsed, dict) or required_key not in parsed:
        return None
    parsed["tokens_input"] = result.get("tokens_input", 0)
    parsed["tokens_output"] = result.get("tokens_output", 0)
    return parsed


def generate_roadmap(title: str, icd10: str, language: str, note: str = "") -> dict | None:
    """Manual/doctor tashxis uchun roadmap (dori qadamsiz — keys §9)."""
    system = "\n\n".join([
        _lang_directive(language),
        _ROADMAP_RULES.format(med_rule=_MED_RULE_NO_MEDS),
    ])
    prompt = f"Tashxis: {title}" + (f" (ICD-10: {icd10})" if icd10 else "")
    if note:
        prompt += f"\nBemor izohi: {note}"
    prompt += "\n\nShu tashxis uchun yo'l xaritasini tuz."
    return _parse(
        generate_text(
            prompt=prompt, system_instruction=system,
            response_schema=ROADMAP_SCHEMA, temperature=0.3,
        ),
        "steps",
    )


def extract_and_build_from_image(
    image_bytes: bytes, image_mime: str, language: str, note: str = ""
) -> dict | None:
    """Tashxis qog'ozi rasmi → extraction + roadmap (bitta chaqiruv)."""
    system = "\n\n".join([
        _lang_directive(language),
        "Sen tibbiy hujjat (tashxis qog'ozi/vypiska/retsept) o'quvchisan. "
        "Avval hujjatni o'qi: recognized_text'ga asosiy matnni ko'chir, "
        "diagnosis_title'ga hujjatdagi ASOSIY tashxisni yoz (o'zing tashxis "
        "QO'YMA — faqat yozilganini o'qi). Hujjat tibbiy bo'lmasa yoki tashxis "
        "topilmasa is_medical_document=false. O'qish qiyin/xira bo'lsa "
        "needs_review=true va confidence'ni past qo'y.",
        _ROADMAP_RULES.format(med_rule=_MED_RULE_FROM_DOC),
    ])
    prompt = "Hujjatni o'qib, tashxisni ajrat va yo'l xaritasini tuz."
    if note:
        prompt += f"\nBemor izohi: {note}"
    return _parse(
        generate_with_image(
            prompt=prompt, image_bytes=image_bytes, image_mime_type=image_mime,
            system_instruction=system, response_schema=FROM_IMAGE_SCHEMA,
            temperature=0.15,
        ),
        "steps",
    )


def triage(complaint: str, diagnosis_context: str, language: str) -> dict | None:
    """Simptom → qaysi mutaxassisga (kontrakt §7)."""
    system = "\n\n".join([
        _lang_directive(language),
        "Sen tibbiy triaj yordamchisisan. Bemor shikoyatini baholab qaysi "
        "mutaxassisga, qanchalik shoshilinch borish kerakligini aytasan.\n"
        "QOIDALAR:\n"
        "- TASHXIS QO'YMA — faqat yo'naltir.\n"
        "- Xavfli belgilar (nafas qisilishi, ko'krak og'rig'i, hushdan ketish, "
        "kuchli qon ketish) → urgency=emergency, birinchi advice 103.\n"
        "- advice — 2-4 amaliy, xavfsiz maslahat (dori nomisiz).\n"
        "- recommended_specialties — 1-3 ta, code kichik harfda "
        "(masalan: kardiolog, gastroenterolog, terapevt).\n"
        "- disclaimer'da bu tashxis emasligini ayt.",
    ])
    prompt = f"Shikoyat: {complaint}"
    if diagnosis_context:
        prompt += f"\n\nBemor konteksti:\n{diagnosis_context}"
    return _parse(
        generate_text(
            prompt=prompt, system_instruction=system,
            response_schema=TRIAGE_SCHEMA, temperature=0.3,
        ),
        "urgency",
    )


def chat_reply(
    message: str, patient_context: str, history: list[dict], language: str
) -> dict | None:
    """Kontekstli AI chat (kontrakt §8). history: [{"role","text"}]."""
    system = "\n\n".join([
        _lang_directive(language),
        "Sen bemorning tashxisdan keyingi yo'l bo'yicha AI yordamchisisan. "
        "Bemor konteksti (tashxis, yo'l xaritasi qadamlari, muolajalar, "
        "ko'rsatkichlar) quyida — javobni SHU kontekstga tayanib ber.\n"
        "QOIDALAR:\n"
        "- TASHXIS QO'YMA, dori TAYINLAMA, dozani O'ZGARTIRMA. Retseptda "
        "yozilgan tartibni tushuntirish mumkin.\n"
        "- Javob qisqa (2-5 jumla), tushunarli, xotirjam.\n"
        "- Savol yo'l xaritasi qadam(lar)iga tegishli bo'lsa ularning id'sini "
        "related_step_ids'ga qo'y (kontekstda [step id=N] shaklida berilgan).\n"
        "- Jiddiy/shaxsiy tibbiy qaror so'ralsa needs_doctor=true va "
        "disclaimer'ga shifokor bilan maslahatlashishni yoz.\n"
        "- Xavfli holat tasvirlansa — javob boshida 103/shifokorga yo'naltir.",
        f"BEMOR KONTEKSTI:\n{patient_context}",
    ])
    return _parse(
        generate_text(
            prompt=message, system_instruction=system, history=history,
            response_schema=CHAT_SCHEMA, temperature=0.4,
        ),
        "reply",
    )
