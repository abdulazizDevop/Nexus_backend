from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminBroadcastViewSet,
    AdminDeviceTokenViewSet,
    DeviceTokenViewSet,
    NotificationViewSet,
)

router = DefaultRouter()
router.register("feed", NotificationViewSet, basename="notification-feed")
router.register("devices", DeviceTokenViewSet, basename="device-token")
router.register("admin/devices", AdminDeviceTokenViewSet, basename="admin-device-token")
router.register("admin/broadcast", AdminBroadcastViewSet, basename="admin-broadcast")

urlpatterns = [
    path("", include(router.urls)),
]
