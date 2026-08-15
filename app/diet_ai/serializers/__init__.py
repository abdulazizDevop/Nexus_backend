"""diet_ai serializerlari — modullarga bo'lingan (import yo'llari o'zgarmaydi).

`from app.diet_ai.serializers import X` ishlaydi — views/ paketi buzilmaydi.
"""

from .conversation import (
    DietConversationCreateSerializer,
    DietConversationDetailSerializer,
    DietConversationListSerializer,
    DietMessageSerializer,
    MessageFeedbackSerializer,
    SendMessageSerializer,
)
from .analyze import (
    AnalyzePhotoSerializer,
    AnalyzeTextSerializer,
    ConfirmCaloriesResponseSerializer,
    ConfirmCaloriesSerializer,
    DailyUsageSerializer,
    PhotoUploadUrlSerializer,
)
from .entry import (
    DietEntryIngredientsEditSerializer,
    DietEntrySerializer,
    IngredientEditItemSerializer,
    ManualDietEntrySerializer,
)
from .profile import (
    DietProfileSerializer,
    DietProfileWriteSerializer,
    DietRestrictionSerializer,
    DietTargetPerMealSerializer,
    DietTargetsSerializer,
)

__all__ = [
    "DietConversationCreateSerializer",
    "DietConversationDetailSerializer",
    "DietConversationListSerializer",
    "DietMessageSerializer",
    "MessageFeedbackSerializer",
    "SendMessageSerializer",
    "AnalyzePhotoSerializer",
    "AnalyzeTextSerializer",
    "ConfirmCaloriesResponseSerializer",
    "ConfirmCaloriesSerializer",
    "DailyUsageSerializer",
    "PhotoUploadUrlSerializer",
    "DietEntryIngredientsEditSerializer",
    "DietEntrySerializer",
    "IngredientEditItemSerializer",
    "ManualDietEntrySerializer",
    "DietProfileSerializer",
    "DietProfileWriteSerializer",
    "DietRestrictionSerializer",
    "DietTargetPerMealSerializer",
    "DietTargetsSerializer",
]
