from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AITrackingReportViewSet

router = DefaultRouter()
router.register("reports", AITrackingReportViewSet, basename="tracking-ai-report")

urlpatterns = [
    path("", include(router.urls)),
]
