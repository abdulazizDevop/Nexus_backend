from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    DailyCalorieLimitViewSet,
    DoctorTreatmentViewSet,
    TreatmentLogViewSet,
    TreatmentViewSet,
)

router = DefaultRouter()
router.register("doctor", DoctorTreatmentViewSet, basename="doctor-treatment")
router.register("calorie", DailyCalorieLimitViewSet, basename="calorie-limit")
router.register("logs", TreatmentLogViewSet, basename="treatment-log")
router.register("", TreatmentViewSet, basename="treatment")

urlpatterns = [
    path("", include(router.urls)),
]
