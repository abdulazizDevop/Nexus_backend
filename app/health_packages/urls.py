from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    DailySituationCheckupViewSet,
    HealthIndicatorTypeViewSet,
    HealthIndicatorViewSet,
)

router = DefaultRouter()
router.register("daily-checkup", DailySituationCheckupViewSet, basename="daily-checkup")
router.register("indicator-types", HealthIndicatorTypeViewSet, basename="indicator-type")
router.register("indicators", HealthIndicatorViewSet, basename="indicator")

urlpatterns = [
    path("", include(router.urls)),
]
