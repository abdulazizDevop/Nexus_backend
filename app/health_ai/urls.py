from rest_framework.routers import DefaultRouter

from .views import AIHealthReportViewSet, AiConversationViewSet

router = DefaultRouter()
router.register(r"reports", AIHealthReportViewSet, basename="health-ai-report")
router.register(
    r"chat/conversations", AiConversationViewSet, basename="health-ai-conversation"
)

urlpatterns = router.urls
