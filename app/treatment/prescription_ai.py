"""Retsept/tashxis qog'ozi rasmini Gemini vision bilan o'qish.

Qat'iy qoida: AI qog'ozda YOZILGANINI ko'chiradi, o'zidan hech narsa
qo'shmaydi — dori tavsiya qilish yo'q, doza "to'ldirish" yo'q. Yakuniy
qaror bemorda (tasdiqlash ekrani) va shifokorda.
"""

from services.gemini import generate_with_image

# Gemini schema — har darajada `required` SHART (services/gemini.py qoidasi).
PRESCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_prescription": {
            "type": "boolean",
            "description": "Rasm retsept/tashxis qog'oziga o'xshaydimi",
        },
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Qog'ozda yozilgan nom, aynan"},
                    "type": {
                        "type": "string",
                        "enum": ["medication", "exercise", "diet", "water", "sleep"],
                    },
                    "dosage": {"type": "string", "description": "Faqat qog'ozda yozilgan doza, bo'lmasa bo'sh"},
                    "times": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Qabul vaqtlari \"HH:MM\". Qog'ozda \"kuniga 2 mahal\" "
                            "bo'lsa 08:00/20:00 kabi standart taqsimla va warnings'da ayt."
                        ),
                    },
                    "repeat": {
                        "type": "string",
                        "enum": [
                            "daily", "every_other_day", "three_times_week",
                            "weekly", "biweekly", "monthly",
                        ],
                    },
                    "duration_days": {
                        "type": "integer",
                        "description": "Qog'ozda muddat yozilgan bo'lsa kunlarda, bo'lmasa 0",
                    },
                    "notes": {"type": "string", "description": "Qog'ozdagi qo'shimcha ko'rsatma (ovqatdan keyin va h.k.)"},
                    "source_text": {"type": "string", "description": "Qog'ozdan o'qilgan asl qator"},
                },
                "required": [
                    "title", "type", "dosage", "times", "repeat",
                    "duration_days", "notes", "source_text",
                ],
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "O'qib bo'lmagan/noaniq joylar, taxmin qilingan vaqtlar",
        },
    },
    "required": ["is_prescription", "summary", "items", "warnings"],
}

_SYSTEM_UZ = """Sen tibbiy retsept/tashxis qog'ozlarini o'qiydigan yordamchisan.
Vazifang: rasmdagi qog'ozda YOZILGAN muolajalarni (dori, mashq, parhez va h.k.)
strukturaga ko'chirish.

QAT'IY QOIDALAR:
- FAQAT qog'ozda aniq yozilganini ko'chir. O'zingdan dori, doza yoki muddat QO'SHMA.
- O'qib bo'lmagan yoki noaniq qatorni items'ga KIRITMA — warnings'ga yoz.
- Doza yozilmagan bo'lsa dosage'ni bo'sh qoldir.
- "Kuniga N mahal" yozilgan bo'lsa vaqtlarni standart taqsimla (1→08:00;
  2→08:00,20:00; 3→08:00,14:00,20:00) va buni warnings'da ayt.
- Rasm retsept/tashxis qog'ozi bo'lmasa is_prescription=false, items=[] qil.
- title'ni qog'ozda yozilganidek qoldir (tarjima qilma).
- summary — 1-2 jumla: qog'ozda umumiy nima yozilgani (bemorga tushunarli)."""


def analyze_prescription_image(image_bytes: bytes, image_mime: str) -> dict:
    """Rasmni tahlil qiladi. Natija: parsed dict + tokenlar, yoki {"error": ...}."""
    import json

    result = generate_with_image(
        prompt="Quyidagi retsept/tashxis qog'ozi rasmini o'qib, strukturaga ko'chir.",
        image_bytes=image_bytes,
        image_mime_type=image_mime,
        system_instruction=_SYSTEM_UZ,
        response_schema=PRESCRIPTION_SCHEMA,
        temperature=0.1,
    )
    if "error" in result:
        return result
    try:
        parsed = json.loads(result.get("text") or "")
    except (ValueError, TypeError):
        return {"error": "AI javobini o'qib bo'lmadi. Qayta urinib ko'ring."}
    if not isinstance(parsed, dict) or "items" not in parsed:
        return {"error": "AI javobi kutilgan formatda emas. Qayta urinib ko'ring."}
    parsed["tokens_input"] = result.get("tokens_input", 0)
    parsed["tokens_output"] = result.get("tokens_output", 0)
    return parsed
