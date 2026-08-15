"""health_packages serializers — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.health_packages.serializers import X` ishlaydi.
"""

from .checkup import (
    DailySituationCheckupSerializer,
)
from .indicator import (
    HealthIndicatorTypeSerializer,
    HealthIndicatorSerializer,
)

__all__ = [
    "DailySituationCheckupSerializer",
    "HealthIndicatorTypeSerializer",
    "HealthIndicatorSerializer",
]
