"""diet_ai services — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.diet_ai.services import X` ishlaydi.
"""

from .nutrition import (
    resolve_targets,
    build_meal_advice,
    has_diet_pro_feature,
    get_diet_progress,
    record_weight,
    MACROS_META,
    get_macros_types,
    add_to_daily_indicators,
    remove_diet_entry_indicators,
    get_daily_summary,
)
from .context import (
    build_user_context,
)
from .usage import (
    FREE_DAILY_LIMIT,
    MAX_MESSAGES_PER_CONVERSATION,
    MAX_HISTORY_MESSAGES,
    is_pro_user,
    check_daily_limit,
    increment_usage,
    should_suggest_new_chat,
    build_history_for_ai,
    auto_generate_title,
)
from .food import (
    parse_food_analysis_response,
    UnknownIngredient,
    estimate_ingredient_per100g,
    recalc_ingredients,
)

__all__ = [
    "resolve_targets",
    "build_meal_advice",
    "has_diet_pro_feature",
    "get_diet_progress",
    "record_weight",
    "MACROS_META",
    "get_macros_types",
    "add_to_daily_indicators",
    "remove_diet_entry_indicators",
    "get_daily_summary",
    "build_user_context",
    "FREE_DAILY_LIMIT",
    "MAX_MESSAGES_PER_CONVERSATION",
    "MAX_HISTORY_MESSAGES",
    "is_pro_user",
    "check_daily_limit",
    "increment_usage",
    "should_suggest_new_chat",
    "build_history_for_ai",
    "auto_generate_title",
    "parse_food_analysis_response",
    "UnknownIngredient",
    "estimate_ingredient_per100g",
    "recalc_ingredients",
]
