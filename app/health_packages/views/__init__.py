"""health_packages view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.health_packages.views import X` ishlashda davom etadi — barcha view
klasslar shu yerda re-export qilinadi. urls.py va tashqi importlar buzilmaydi.
"""

from .checkup import DailySituationCheckupViewSet
from .indicator_types import HealthIndicatorTypeViewSet
from .indicators import HealthIndicatorViewSet

__all__ = [
    "DailySituationCheckupViewSet",
    "HealthIndicatorTypeViewSet",
    "HealthIndicatorViewSet",
]
