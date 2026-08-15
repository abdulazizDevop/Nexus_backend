from django.urls import include, path
from rest_framework.routers import DefaultRouter

from app.pharmacy.views import DrugViewSet

router = DefaultRouter()
router.register("drugs", DrugViewSet, basename="drug")

urlpatterns = [
    path("", include(router.urls)),
]
