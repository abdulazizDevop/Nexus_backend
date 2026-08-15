from django.urls import path, include
from rest_framework.routers import DefaultRouter

from app.auth.views import AuthViewSet, TokenRefreshView

router = DefaultRouter()
router.register("", AuthViewSet, basename="auth")

urlpatterns = [
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("", include(router.urls)),
]
