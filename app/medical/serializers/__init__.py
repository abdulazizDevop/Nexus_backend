"""medical serializerlari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.medical.serializers import X` ishlaydi. Views (analysis.py, card.py) lazy
import qiladigan helperlar ham re-export: ui_status_q, _compute_ui_status, _signed_download.
"""

from .common import _compute_ui_status, _signed_download, ui_status_q
from .condition import (
    MedicalConditionSerializer,
)
from .card import (
    MedicalCardSerializer,
    MedicalCardSummarySerializer,
)
from .note import (
    AudioUploadUrlRequestSerializer,
    AudioUploadUrlResponseSerializer,
    MedicalNoteAIDraftRequestSerializer,
    MedicalNoteAIDraftResponseSerializer,
    MedicalNoteImageSerializer,
    MedicalNoteImageUploadUrlRequestSerializer,
    MedicalNoteImageUploadUrlResponseSerializer,
    MedicalNoteSerializer,
)
from .analysis import (
    AnalysisDetailSerializer,
    AnalysisFileSerializer,
    AnalysisIndicatorSerializer,
    AnalysisListSerializer,
    AnalysisPreparationSerializer,
    AnalysisResultSerializer,
    AnalysisResultValueSerializer,
    AnalysisTypeSerializer,
)
from .analysis_actions import (
    AnalysisCancelSerializer,
    AnalysisCreateSerializer,
    AnalysisMarkSeenByDoctorResponseSerializer,
    AnalysisResultUploadUrlRequestSerializer,
    AnalysisResultUploadUrlResponseSerializer,
    AnalysisReviewSerializer,
    AnalysisSubmitSerializer,
    AnalysisUpdateSerializer,
)
from .patient_analysis import (
    PatientAnalysisCreateSerializer,
    PatientAnalysisUploadUrlRequestSerializer,
    PatientAnalysisUploadUrlResponseSerializer,
)

__all__ = [
    "MedicalConditionSerializer",
    "MedicalCardSerializer",
    "MedicalCardSummarySerializer",
    "AudioUploadUrlRequestSerializer",
    "AudioUploadUrlResponseSerializer",
    "MedicalNoteAIDraftRequestSerializer",
    "MedicalNoteAIDraftResponseSerializer",
    "MedicalNoteImageSerializer",
    "MedicalNoteImageUploadUrlRequestSerializer",
    "MedicalNoteImageUploadUrlResponseSerializer",
    "MedicalNoteSerializer",
    "AnalysisDetailSerializer",
    "AnalysisFileSerializer",
    "AnalysisIndicatorSerializer",
    "AnalysisListSerializer",
    "AnalysisPreparationSerializer",
    "AnalysisResultSerializer",
    "AnalysisResultValueSerializer",
    "AnalysisTypeSerializer",
    "AnalysisCancelSerializer",
    "AnalysisCreateSerializer",
    "AnalysisMarkSeenByDoctorResponseSerializer",
    "AnalysisResultUploadUrlRequestSerializer",
    "AnalysisResultUploadUrlResponseSerializer",
    "AnalysisReviewSerializer",
    "AnalysisSubmitSerializer",
    "AnalysisUpdateSerializer",
    "PatientAnalysisCreateSerializer",
    "PatientAnalysisUploadUrlRequestSerializer",
    "PatientAnalysisUploadUrlResponseSerializer",
    "ui_status_q",
    "_compute_ui_status",
    "_signed_download",
]
