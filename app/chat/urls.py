from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    ChatRoomViewSet,
    AdminChatRoomViewSet,
    OnlineStatusView,
    SupportChatViewSet,
)

router = DefaultRouter()
router.register("rooms", ChatRoomViewSet, basename="chat-room")
router.register("support", SupportChatViewSet, basename="support-chat")
router.register("admin/rooms", AdminChatRoomViewSet, basename="admin-chat-room")
router.register("online-status", OnlineStatusView, basename="online-status")

urlpatterns = [
    path("", include(router.urls)),
]
