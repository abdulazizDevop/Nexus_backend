"""medical models — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.medical.models import X` ishlaydi (Django app-registry models uchun __init__ hammasini import qiladi).
"""

from .card import (
    MedicalCard,
)
from .condition import (
    MedicalCondition,
)
from .roadmap import (
    RoadmapStep,
)
from .note import (
    MedicalNote,
    MedicalNoteImage,
)
from .analysis import (
    Analysis,
    AnalysisFile,
    AnalysisIndicator,
    AnalysisPreparation,
    AnalysisResult,
    AnalysisResultValue,
    AnalysisType,
)

__all__ = [
    "MedicalCard",
    "MedicalCondition",
    "RoadmapStep",
    "MedicalNote",
    "MedicalNoteImage",
    "Analysis",
    "AnalysisFile",
    "AnalysisIndicator",
    "AnalysisPreparation",
    "AnalysisResult",
    "AnalysisResultValue",
    "AnalysisType",
]
