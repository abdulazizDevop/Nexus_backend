from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminDietConversationViewSet,
    DietAnalyzePhotoView,
    DietAnalyzeTextView,
    DietConfirmCaloriesView,
    DietConversationViewSet,
    DietDailySummaryView,
    DietEntryDeleteView,
    DietHistoryView,
    DietManualEntryView,
    DietMessageFeedbackView,
    DietMyRestrictionsView,
    DietProfileView,
    DietProgressView,
    DietTargetsView,
    DietTipTodayView,
    DietPhotoUploadUrlView,
    DietUsageView,
    DoctorDietConversationViewSet,
    DoctorDietRestrictionViewSet,
    DoctorPatientDietHistoryView,
    DoctorPatientRestrictionsView,
)

# --- Patient routers ---
patient_router = DefaultRouter()
patient_router.register(
    r"conversations", DietConversationViewSet, basename="diet-conversations"
)

# --- Doctor routers ---
doctor_router = DefaultRouter()
doctor_router.register(
    r"restrictions", DoctorDietRestrictionViewSet, basename="diet-restrictions"
)

# --- Admin routers ---
admin_router = DefaultRouter()
admin_router.register(
    r"conversations", AdminDietConversationViewSet, basename="diet-admin-conversations"
)


urlpatterns = [
    # Patient
    path("", include(patient_router.urls)),
    path("upload-url/", DietPhotoUploadUrlView.as_view(), name="diet-upload-url"),
    path("analyze-photo/", DietAnalyzePhotoView.as_view(), name="diet-analyze-photo"),
    path("analyze-text/", DietAnalyzeTextView.as_view(), name="diet-analyze-text"),
    path(
        "messages/<int:message_id>/confirm-calories/",
        DietConfirmCaloriesView.as_view(),
        name="diet-confirm-calories",
    ),
    path(
        "messages/<int:message_id>/feedback/",
        DietMessageFeedbackView.as_view(),
        name="diet-message-feedback",
    ),
    path("usage-today/", DietUsageView.as_view(), name="diet-usage"),
    path("profile/", DietProfileView.as_view(), name="diet-profile"),
    path("targets/", DietTargetsView.as_view(), name="diet-targets"),
    path("progress/", DietProgressView.as_view(), name="diet-progress"),
    path(
        "manual-entry/",
        DietManualEntryView.as_view(),
        name="diet-manual-entry",
    ),
    path("history/", DietHistoryView.as_view(), name="diet-history"),
    path(
        "history/<int:entry_id>/",
        DietEntryDeleteView.as_view(),
        name="diet-history-delete",
    ),
    path(
        "daily-summary/",
        DietDailySummaryView.as_view(),
        name="diet-daily-summary",
    ),
    path("tip-today/", DietTipTodayView.as_view(), name="diet-tip-today"),
    path(
        "my-restrictions/",
        DietMyRestrictionsView.as_view(),
        name="diet-my-restrictions",
    ),
    # Doctor
    path("doctor/", include(doctor_router.urls)),
    path(
        "doctor/patients/<int:patient_id>/restrictions/",
        DoctorPatientRestrictionsView.as_view(),
        name="diet-doctor-patient-restrictions",
    ),
    path(
        "doctor/patients/<int:patient_id>/history/",
        DoctorPatientDietHistoryView.as_view(),
        name="diet-doctor-patient-history",
    ),
    path(
        "doctor/patients/<int:patient_id>/conversations/",
        DoctorDietConversationViewSet.as_view({"get": "list"}),
        name="diet-doctor-patient-conversations",
    ),
    path(
        "doctor/patients/<int:patient_id>/conversations/<int:pk>/",
        DoctorDietConversationViewSet.as_view({"get": "retrieve"}),
        name="diet-doctor-patient-conversation-detail",
    ),
    # Admin
    path("admin/", include(admin_router.urls)),
]
