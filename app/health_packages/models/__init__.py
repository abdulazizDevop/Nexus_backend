"""health_packages models — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.health_packages.models import X` ishlaydi.
"""

from .indicator import (
    HealthIndicatorType,
    HealthIndicator,
)
from .checkup import (
    DailySituationCheckup,
)

__all__ = [
    "HealthIndicatorType",
    "HealthIndicator",
    "DailySituationCheckup",
]
