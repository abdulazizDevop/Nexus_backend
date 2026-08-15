"""treatment views — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.treatment.views import X` ishlaydi — urls.py buzilmaydi.
"""

from .treatment import (
    TreatmentLogViewSet,
    TreatmentViewSet,
)
from .doctor import (
    DoctorTreatmentViewSet,
)
from .calorie import (
    DailyCalorieLimitViewSet,
)
from .prescription import (
    PrescriptionScanViewSet,
    PrescriptionUploadUrlView,
)

__all__ = [
    "TreatmentLogViewSet",
    "TreatmentViewSet",
    "DoctorTreatmentViewSet",
    "DailyCalorieLimitViewSet",
    "PrescriptionScanViewSet",
    "PrescriptionUploadUrlView",
]
