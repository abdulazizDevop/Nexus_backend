from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminDoctorSlotsView,
    DoctorCertificateViewSet,
    DoctorMeSlotsSyncView,
    DoctorMeSlotsView,
    DoctorProfileViewSet,
    PublicDoctorSlotsView,
    SpecialtyViewSet,
)

router = DefaultRouter()
router.register("specialties", SpecialtyViewSet, basename="specialty")
router.register("profiles", DoctorProfileViewSet, basename="doctor-profile")
router.register("certificates", DoctorCertificateViewSet, basename="doctor-certificate")

urlpatterns = [
    path("me/slots/", DoctorMeSlotsView.as_view(), name="me-slots"),
    path("me/slots/sync/", DoctorMeSlotsSyncView.as_view(), name="me-slots-sync"),
    path(
        "admin/<int:doctor_id>/slots/",
        AdminDoctorSlotsView.as_view(),
        name="admin-doctor-slots",
    ),
    path(
        "<int:doctor_id>/slots/",
        PublicDoctorSlotsView.as_view(),
        name="public-doctor-slots",
    ),
    path("", include(router.urls)),
]
