from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ReviewTagViewSet, ReviewViewSet

router = DefaultRouter()
router.register("reviews", ReviewViewSet, basename="review")
router.register("tags", ReviewTagViewSet, basename="review-tag")

urlpatterns = [
    path("", include(router.urls)),
]
