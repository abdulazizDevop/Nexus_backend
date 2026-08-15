from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import GuideVideoAdminViewSet, GuideVideoListView

router = DefaultRouter()
router.register("admin/guides", GuideVideoAdminViewSet, basename="admin-guide")

urlpatterns = [
    # Mobil — faol videolar ro'yxati
    path("guides/", GuideVideoListView.as_view(), name="guides-list"),
    # Admin CRUD — /admin/guides/
    path("", include(router.urls)),
]
