from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AdminAppointmentViewSet,
    ConsultationViewSet,
    DoctorAppointmentViewSet,
    PatientAppointmentViewSet,
)

router = DefaultRouter()
router.register("patient", PatientAppointmentViewSet, basename="patient-appointment")
router.register("doctor", DoctorAppointmentViewSet, basename="doctor-appointment")
router.register("admin", AdminAppointmentViewSet, basename="admin-appointment")
router.register("consultations", ConsultationViewSet, basename="consultation")

urlpatterns = [
    path("", include(router.urls)),
]
