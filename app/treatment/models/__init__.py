"""treatment models — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.treatment.models import X` ishlaydi.
"""

from .treatment import (
    Treatment,
    TreatmentLog,
)
from .calorie import (
    DailyCalorieLimit,
)
from .prescription import (
    PrescriptionScan,
)

__all__ = [
    "Treatment",
    "TreatmentLog",
    "DailyCalorieLimit",
    "PrescriptionScan",
]
