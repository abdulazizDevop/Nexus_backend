"""diet_ai prompts — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.diet_ai.prompts import X` ishlaydi.
"""

from .rules import (
    BASE_RULES_UZ,
    BASE_RULES_UZ_CYRL,
    BASE_RULES_RU,
    get_base_rules,
)
from .photo import (
    PHOTO_ANALYSIS_UZ,
    PHOTO_ANALYSIS_RU,
    PHOTO_ANALYSIS_UZ_CYRL,
    get_photo_analysis_prompt,
)
from .text import (
    TEXT_ANALYSIS_UZ,
    TEXT_ANALYSIS_RU,
    TEXT_ANALYSIS_UZ_CYRL,
    get_text_analysis_prompt,
)
from .schema import (
    FOOD_ANALYSIS_SCHEMA,
)
from .system import (
    DIET_CHAT_LANG_DIRECTIVE,
    build_system_prompt,
)

__all__ = [
    "BASE_RULES_UZ",
    "BASE_RULES_UZ_CYRL",
    "BASE_RULES_RU",
    "get_base_rules",
    "PHOTO_ANALYSIS_UZ",
    "PHOTO_ANALYSIS_RU",
    "PHOTO_ANALYSIS_UZ_CYRL",
    "get_photo_analysis_prompt",
    "TEXT_ANALYSIS_UZ",
    "TEXT_ANALYSIS_RU",
    "TEXT_ANALYSIS_UZ_CYRL",
    "get_text_analysis_prompt",
    "FOOD_ANALYSIS_SCHEMA",
    "DIET_CHAT_LANG_DIRECTIVE",
    "build_system_prompt",
]
