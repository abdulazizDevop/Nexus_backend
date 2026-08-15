from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AnalysisIndicatorViewSet,
    AnalysisPreparationViewSet,
    AnalysisTypeViewSet,
    AnalysisViewSet,
    MedicalAudioUploadUrlView,
    MedicalCardSummaryView,
    MedicalCardViewSet,
    MedicalConditionViewSet,
    MedicalNoteAIDraftView,
    MedicalNoteImageUploadUrlView,
    MedicalNoteViewSet,
)

router = DefaultRouter()
router.register("card", MedicalCardViewSet, basename="medical-card")
router.register("conditions", MedicalConditionViewSet, basename="medical-condition")
router.register("notes", MedicalNoteViewSet, basename="medical-note")
router.register("analysis-types", AnalysisTypeViewSet, basename="analysis-type")
router.register(
    "analysis-indicators",
    AnalysisIndicatorViewSet,
    basename="analysis-indicator",
)
router.register(
    "analysis-preparations",
    AnalysisPreparationViewSet,
    basename="analysis-preparation",
)
router.register("analyses", AnalysisViewSet, basename="analysis")

urlpatterns = [
    # Custom endpointlar router.urls'dan OLDIN bo'lishi shart —
    # aks holda 'notes/audio-upload-url/' router'ning 'notes/<pk>/' bilan to'qnashadi
    # va pk="audio-upload-url" deb interpretatsiya qilinadi.
    path(
        "notes/audio-upload-url/",
        MedicalAudioUploadUrlView.as_view(),
        name="medical-audio-upload-url",
    ),
    path(
        "notes/image-upload-url/",
        MedicalNoteImageUploadUrlView.as_view(),
        name="medical-note-image-upload-url",
    ),
    path(
        "notes/ai-draft/",
        MedicalNoteAIDraftView.as_view(),
        name="medical-note-ai-draft",
    ),
    path(
        "patients/<int:patient_id>/card-summary/",
        MedicalCardSummaryView.as_view(),
        name="medical-card-summary",
    ),
    path("", include(router.urls)),
]
