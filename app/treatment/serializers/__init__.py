"""treatment serializers — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.treatment.serializers import X` ishlaydi.
"""

from .treatment import (
    TreatmentSerializer,
    DoctorTreatmentCreateSerializer,
)
from .calorie import (
    DailyCalorieLimitSerializer,
    DailyCalorieLimitSetSerializer,
)
from .log import (
    TreatmentLogSerializer,
    TreatmentMarkSerializer,
    TreatmentStatsSerializer,
)
from .prescription import (
    PrescriptionAnalyzeSerializer,
    PrescriptionConfirmSerializer,
    PrescriptionItemSerializer,
    PrescriptionScanSerializer,
    PrescriptionUploadUrlSerializer,
)
from .common import _validate_doctor_patient_link  # noqa: F401

__all__ = [
    "TreatmentSerializer",
    "DoctorTreatmentCreateSerializer",
    "DailyCalorieLimitSerializer",
    "DailyCalorieLimitSetSerializer",
    "TreatmentLogSerializer",
    "TreatmentMarkSerializer",
    "TreatmentStatsSerializer",
    "PrescriptionUploadUrlSerializer",
    "PrescriptionAnalyzeSerializer",
    "PrescriptionItemSerializer",
    "PrescriptionConfirmSerializer",
    "PrescriptionScanSerializer",
]
