from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    DailyCalorieLimitViewSet,
    DoctorTreatmentViewSet,
    PrescriptionScanViewSet,
    PrescriptionUploadUrlView,
    TreatmentLogViewSet,
    TreatmentViewSet,
)

router = DefaultRouter()
router.register("doctor", DoctorTreatmentViewSet, basename="doctor-treatment")
router.register("calorie", DailyCalorieLimitViewSet, basename="calorie-limit")
router.register("logs", TreatmentLogViewSet, basename="treatment-log")
# MUHIM: "" (TreatmentViewSet) registratsiyasidan OLDIN — yo'l soyalanmasin.
router.register("prescription", PrescriptionScanViewSet, basename="prescription-scan")
router.register("", TreatmentViewSet, basename="treatment")

urlpatterns = [
    path(
        "prescription/upload-url/",
        PrescriptionUploadUrlView.as_view(),
        name="prescription-upload-url",
    ),
    path("", include(router.urls)),
]
