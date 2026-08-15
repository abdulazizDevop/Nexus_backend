"""diet_ai view'lari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.diet_ai.views import X` ishlashda davom etadi — urls.py buzilmaydi.
"""

from .admin import AdminDietConversationViewSet
from .analysis import (
    DietAnalyzePhotoView,
    DietAnalyzeTextView,
    DietPhotoUploadUrlView,
)
from .chat import DietConversationViewSet
from .doctor import (
    DoctorDietConversationViewSet,
    DoctorDietRestrictionViewSet,
    DoctorPatientDietHistoryView,
    DoctorPatientRestrictionsView,
)
from .entries import (
    DietConfirmCaloriesView,
    DietManualEntryView,
    DietMessageFeedbackView,
)
from .history import (
    DietDailySummaryView,
    DietEntryDeleteView,
    DietHistoryView,
)
from .profile import (
    DietProfileView,
    DietProgressView,
    DietTargetsView,
    DietUsageView,
)
from .tips import DietMyRestrictionsView, DietTipTodayView

__all__ = [
    "DietConversationViewSet",
    "DietPhotoUploadUrlView",
    "DietAnalyzePhotoView",
    "DietAnalyzeTextView",
    "DietUsageView",
    "DietProfileView",
    "DietTargetsView",
    "DietProgressView",
    "DietConfirmCaloriesView",
    "DietMessageFeedbackView",
    "DietManualEntryView",
    "DietHistoryView",
    "DietEntryDeleteView",
    "DietDailySummaryView",
    "DietTipTodayView",
    "DietMyRestrictionsView",
    "DoctorDietRestrictionViewSet",
    "DoctorPatientRestrictionsView",
    "DoctorPatientDietHistoryView",
    "DoctorDietConversationViewSet",
    "AdminDietConversationViewSet",
]
