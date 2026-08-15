from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

FOOD_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "food_detected": {
            "type": "boolean",
            "description": "Rasmda ovqat borligini tasdiqlaydi. False bo'lsa food_data raqamlari 0.",
        },
        "analysis_markdown": {
            "type": "string",
            "description": (
                "Markdown formatidagi tahlil matni. food_detected=false bo'lsa — "
                "'Rasmda ovqat ko'rsatilmagan. Iltimos, ovqat rasmini yuklang.'"
            ),
        },
        "food_data": {
            "type": "object",
            "properties": {
                "food_name": {"type": "string"},
                "estimated_calories": {"type": "integer"},
                "portion_grams": {"type": "integer", "nullable": True},
                "carbs_grams": {"type": "integer"},
                "protein_grams": {"type": "integer"},
                "fat_grams": {"type": "integer"},
                "glycemic_load": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "nullable": True,
                    "description": "Taomning glikemik yuki (past-GI diabet nazorati uchun).",
                },
                "ingredients": {
                    "type": "array",
                    "description": (
                        "Taomning 3-10 ta asosiy ingredienti; har birida gramm + "
                        "kaloriya + makro. Yig'indisi umumiy qiymatlarga teng bo'lsin (±5%)."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "grams": {"type": "integer"},
                            "calories": {"type": "integer"},
                            "carbs_g": {"type": "integer"},
                            "protein_g": {"type": "integer"},
                            "fat_g": {"type": "integer"},
                        },
                        "required": ["name", "grams", "calories", "carbs_g", "protein_g", "fat_g"],
                    },
                },
            },
            # food_data + ichki maydonlar MAJBURIY. Aks holда (avval nullable + required
            # emas edi) Gemini raqamlarni faqat analysis_markdown matniga yozib,
            # structured food_data'ни bo'sh qoldirardi → app'da calories=0/food="" bug.
            # Ovqat yo'q bo'lsa: hamma raqam 0, food_name "" (food_detected=false bilan).
            "required": [
                "food_name",
                "estimated_calories",
                "carbs_grams",
                "protein_grams",
                "fat_grams",
            ],
        },
    },
    "required": ["food_detected", "analysis_markdown", "food_data"],
}


# Chat uchun — model FOYDALANUVCHI tiliga moslashadi (conversation.language qat'iy emas).
