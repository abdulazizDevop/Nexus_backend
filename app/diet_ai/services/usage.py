from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

FREE_DAILY_LIMIT = 10

MAX_MESSAGES_PER_CONVERSATION = 30  # bu chegaraga yetsa yangi chat ochish tavsiya

MAX_HISTORY_MESSAGES = 10  # Context token'ni kamaytirish uchun oxirgi 10 ta

def is_pro_user(user) -> bool:
    """Pro obunada cheksiz diet AI mavjudligini tekshiradi."""
    try:
        return has_pro_feature(user, "unlimited_diet_ai")
    except Exception:
        # payments app hali sozlanmagan bo'lsa — bepul limit bilan ketamiz
        return False

def check_daily_limit(user) -> dict:
    """Bugungi limit tekshiruvi.

    Returns:
        {
            "allowed": bool,
            "used": int,
            "limit": int | None (None = cheksiz),
            "remaining": int | None,
        }
    """
    if is_pro_user(user):
        return {"allowed": True, "used": 0, "limit": None, "remaining": None}

    today = timezone.localdate()
    usage = DietDailyUsage.objects.filter(user=user, date=today).first()
    used = usage.questions_count if usage else 0

    return {
        "allowed": used < FREE_DAILY_LIMIT,
        "used": used,
        "limit": FREE_DAILY_LIMIT,
        "remaining": max(0, FREE_DAILY_LIMIT - used),
    }

def increment_usage(user, tokens_input: int = 0, tokens_output: int = 0) -> None:
    """Kunlik ishlatishni +1 oshirish (atomic upsert).

    Avval F() update urinadi (mavjud qator bo'lsa, race'siz). Qator yo'q bo'lsa
    create qiladi; bir vaqtli so'rov IntegrityError bersa — qayta update qilamiz.
    Bu CLAUDE.md'dagi upsert qoidasiga mos (unique_together=(user, date)).
    """
    from django.db import IntegrityError

    today = timezone.localdate()
    updated = DietDailyUsage.objects.filter(user=user, date=today).update(
        questions_count=F("questions_count") + 1,
        tokens_input=F("tokens_input") + tokens_input,
        tokens_output=F("tokens_output") + tokens_output,
    )
    if updated:
        return
    try:
        DietDailyUsage.objects.create(
            user=user,
            date=today,
            questions_count=1,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
        )
    except IntegrityError:
        # Boshqa so'rov bizdan oldin yaratdi — endi update qilamiz
        DietDailyUsage.objects.filter(user=user, date=today).update(
            questions_count=F("questions_count") + 1,
            tokens_input=F("tokens_input") + tokens_input,
            tokens_output=F("tokens_output") + tokens_output,
        )

def should_suggest_new_chat(conversation: DietConversation) -> bool:
    """Suhbat xabarlar soni chegaraga yetgan bo'lsa, yangi chat ochish tavsiyasi."""
    return conversation.messages.count() >= MAX_MESSAGES_PER_CONVERSATION

def build_history_for_ai(
    conversation: DietConversation, limit: int = MAX_HISTORY_MESSAGES
) -> list[dict]:
    """Oldingi xabarlarni Gemini formatida qaytaradi (oxirgi N ta).

    Gemini format: [{"role": "user|model", "text": "..."}]
    """
    messages = list(
        reversed(
            list(
                conversation.messages.exclude(is_blocked=True)
                .order_by("-created_at")[:limit]
            )
        )
    )

    history = []
    for msg in messages:
        if msg.role == "user":
            history.append({"role": "user", "text": msg.content})
        elif msg.role == "assistant":
            history.append({"role": "model", "text": msg.content})
    return history

def auto_generate_title(first_question: str, max_length: int = 60) -> str:
    """Birinchi savoldan suhbat nomini yaratadi."""
    clean = first_question.strip().replace("\n", " ")
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 3] + "..."


# --- Kaloriya + Macros yordamchi funksiyalari ---
