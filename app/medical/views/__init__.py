"""medical view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.medical.views import X` ishlashda davom etadi — urls.py buzilmaydi.
"""

from .ai import MedicalAudioUploadUrlView, MedicalNoteAIDraftView
from .analysis import AnalysisViewSet
from .card import MedicalCardSummaryView, MedicalCardViewSet
from .catalog import (
    AnalysisIndicatorViewSet,
    AnalysisPreparationViewSet,
    AnalysisTypeViewSet,
)
from .conditions import MedicalConditionViewSet
from .notes import MedicalNoteImageUploadUrlView, MedicalNoteViewSet

__all__ = [
    "MedicalCardViewSet",
    "MedicalCardSummaryView",
    "MedicalConditionViewSet",
    "MedicalNoteViewSet",
    "MedicalNoteImageUploadUrlView",
    "MedicalAudioUploadUrlView",
    "MedicalNoteAIDraftView",
    "AnalysisTypeViewSet",
    "AnalysisIndicatorViewSet",
    "AnalysisPreparationViewSet",
    "AnalysisViewSet",
]
