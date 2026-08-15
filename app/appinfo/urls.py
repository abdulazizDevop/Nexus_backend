from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MobileAppInfoAdminViewSet

router = DefaultRouter()
router.register(
    "admin/mobile-info", MobileAppInfoAdminViewSet, basename="admin-mobile-info"
)

# Eslatma: publik `GET /info/mobile/` config/urls.py root'iga ulanadi (/api/v1/ emas).
urlpatterns = [
    path("", include(router.urls)),
]
