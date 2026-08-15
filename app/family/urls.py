from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import FamilyDailyReportView, FamilyLinkViewSet, FamilyMemberSideViewSet

router = DefaultRouter()
# Bemor tomoni: GET members/ (list), POST members/invite/, DELETE members/{id}/
router.register("members", FamilyLinkViewSet, basename="family-member")
# A'zo tomoni: GET me/invitations/, POST me/{id}/accept|decline/, GET me/patients/
router.register("me", FamilyMemberSideViewSet, basename="family-me")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "patients/<int:patient_id>/daily-report/",
        FamilyDailyReportView.as_view(),
        name="family-daily-report",
    ),
]
