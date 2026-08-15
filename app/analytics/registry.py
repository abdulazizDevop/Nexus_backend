"""Feature registry — analitika 'feature'lari va ularning manbalari.

Har feature ikki manbadan hisoblanadi:
  1) TARIXIY (deploygacha ham) — mavjud domen yozuvlaridan: `model` + `ts_field`.
     Bu darhol butun tarixiy data'da ishlaydi (migration/instrumentatsiya shart emas).
  2) KELAJAK (deploydan keyin) — `FeatureUsageDaily` event jadvalidan; middleware
     `path_prefixes` bo'yicha har so'rovni feature'ga map qilib yozib boradi.

`user_field` — User'ga ishora qiluvchi maydon yoki lookup (mas. "conversation__user_id").
`has_time` — ts_field DateTime bo'lsa True (soat-heatmap uchun), DateField bo'lsa False.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    category: str
    model: str  # dotted path
    user_field: str
    ts_field: str
    has_time: bool = True
    extra_filter: dict = field(default_factory=dict)
    path_prefixes: tuple = ()


# Kategoriya belgilari (frontend segmentatsiya + rang uchun)
CATEGORIES = {
    "consultation": "Konsultatsiya",
    "diet": "Parhez (AI)",
    "treatment": "Muolaja",
    "health": "Sog'liq",
    "communication": "Aloqa",
    "engagement": "Faollik",
    "monetization": "To'lov",
}


FEATURES = [
    Feature(
        "appointment", "Qabulga yozilish", "consultation",
        "app.meetings.models.Appointment", "patient_id", "created_at",
        path_prefixes=("/api/v1/meetings/patient",),
    ),
    Feature(
        "diet_entry", "Diet — ovqat kiritish", "diet",
        "app.diet_ai.models.DietEntry", "user_id", "created_at",
        path_prefixes=(
            "/api/v1/diet/manual-entry",
            "/api/v1/diet/analyze-photo",
            "/api/v1/diet/analyze-text",
        ),
    ),
    Feature(
        "diet_chat", "Diet — AI suhbat", "diet",
        "app.diet_ai.models.DietMessage", "conversation__user_id", "created_at",
        extra_filter={"role": "user"},
        path_prefixes=("/api/v1/diet/conversations",),
    ),
    Feature(
        "treatment", "Muolaja qo'shish", "treatment",
        "app.treatment.models.Treatment", "user_id", "created_at",
    ),
    Feature(
        "treatment_log", "Muolaja bajarish", "treatment",
        "app.treatment.models.TreatmentLog", "user_id", "date", has_time=False,
    ),
    Feature(
        "health_manual", "Sog'liq — qo'lda", "health",
        "app.health_packages.models.HealthIndicator", "user_id", "recorded_at",
        extra_filter={"source": "manual"},
    ),
    Feature(
        "checkup", "Kunlik holat", "health",
        "app.health_packages.models.DailySituationCheckup", "user_id", "date",
        has_time=False,
    ),
    Feature(
        "chat_message", "Chat xabar", "communication",
        "app.chat.models.Message", "sender_id", "created_at",
    ),
    Feature(
        "call", "Qo'ng'iroq", "communication",
        "app.chat.models.CallSession", "caller_id", "created_at",
    ),
    Feature(
        "review", "Sharh yozish", "engagement",
        "app.feedbacks.models.Review", "patient_id", "created_at",
    ),
    Feature(
        "payment", "To'lov", "monetization",
        "app.payments.models.Payment", "user_id", "created_at",
        extra_filter={"status": "completed"},
    ),
]

FEATURES_BY_KEY = {f.key: f for f in FEATURES}

# Event middleware (Phase 2) uchun — URL prefiksi → feature key (eng uzun mos).
# Faqat path_prefixes belgilangan feature'lar "engagement touch" sifatida yoziladi.
ENGAGEMENT_MAP = tuple(
    (prefix, f.key)
    for f in FEATURES
    for prefix in f.path_prefixes
)


def feature_for_path(path: str):
    """URL path'ga mos feature key (eng uzun prefiks). Mos kelmasa None."""
    best = None
    for prefix, key in ENGAGEMENT_MAP:
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), key)
    return best[1] if best else None
