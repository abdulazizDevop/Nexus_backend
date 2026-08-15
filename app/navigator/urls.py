from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ActiveRoadmapView,
    NavigatorChatView,
    NavigatorDiagnosisViewSet,
    StepCompleteView,
    TriageView,
)

router = DefaultRouter()
# list/retrieve/create + from-image action
router.register("diagnoses", NavigatorDiagnosisViewSet, basename="navigator-diagnosis")

urlpatterns = [
    path("roadmap/active/", ActiveRoadmapView.as_view(), name="navigator-roadmap-active"),
    path(
        "steps/<int:pk>/complete/",
        StepCompleteView.as_view(),
        name="navigator-step-complete",
    ),
    path("triage/", TriageView.as_view(), name="navigator-triage"),
    path("chat/", NavigatorChatView.as_view(), name="navigator-chat"),
    path("", include(router.urls)),
]
