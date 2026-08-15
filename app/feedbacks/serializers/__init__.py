"""feedbacks serializers — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.feedbacks.serializers import X` ishlaydi.
"""

from .read import (
    DEFAULT_DISPLAY_NAME,
    ReviewTagSerializer,
    ReviewSerializer,
)
from .write import (
    ReviewCreateSerializer,
    ReviewUpdateSerializer,
)
from .common import CRITICAL_MAX_RATING, POSITIVE_MIN_RATING  # noqa: F401

__all__ = [
    "DEFAULT_DISPLAY_NAME",
    "ReviewTagSerializer",
    "ReviewSerializer",
    "ReviewCreateSerializer",
    "ReviewUpdateSerializer",
    "CRITICAL_MAX_RATING",
    "POSITIVE_MIN_RATING",
]
