"""diet_ai models — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.diet_ai.models import X` ishlaydi.
"""

from .conversation import (
    HAS_IMAGE,
    DietMessageQuerySet,
    DietConversation,
    DietMessage,
    DietEntry,
)
from .restriction import (
    DietRestriction,
)
from .usage import (
    DietDailyUsage,
)
from .profile import (
    DietProfile,
)

__all__ = [
    "HAS_IMAGE",
    "DietMessageQuerySet",
    "DietConversation",
    "DietMessage",
    "DietEntry",
    "DietRestriction",
    "DietDailyUsage",
    "DietProfile",
]
