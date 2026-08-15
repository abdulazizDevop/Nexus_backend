"""Chat AI gatekeeper konstantalari."""

# Kunlik AI avto-javob limiti (har bemor↔doctor juftligiga). SystemSetting'dan
# o'zgartiriladi — bu default.
CHAT_AI_DAILY_CAP_KEY = "chat_ai_daily_cap"
CHAT_AI_DAILY_CAP_DEFAULT = 10

# Gemini'ga beriladigan oxirgi N ta text xabar (kontekst token cheklovi).
CHAT_AI_HISTORY_LIMIT = 10
