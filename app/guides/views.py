from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from core.permissions import IsSuperOrSimpleAdmin

from .models import GuideVideo
from .serializers import GuideVideoSerializer


@extend_schema(tags=["Guides - Video qo'llanmalar"])
class GuideVideoListView(ListAPIView):
    """Mobil — faol video qo'llanmalar ro'yxati (app_scope bo'yicha).

    `?app_scope=doctor|patient` — shu scope YOKI `both` bo'lgan, `is_active=True`
    videolar `order` bo'yicha qaytadi. `?lang=` (global) bo'yicha til tanlanadi.
    """

    serializer_class = GuideVideoSerializer
    permission_classes = [IsAuthenticated]
    queryset = GuideVideo.objects.none()

    @extend_schema(
        summary="Video qo'llanmalar ro'yxati",
        parameters=[
            OpenApiParameter(
                "app_scope", str, description="doctor | patient (bo'sh = hammasi)"
            ),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GuideVideo.objects.none()
        qs = GuideVideo.objects.filter(is_active=True)
        scope = self.request.query_params.get("app_scope")
        if scope in (GuideVideo.AppScope.DOCTOR, GuideVideo.AppScope.PATIENT):
            qs = qs.filter(Q(app_scope=scope) | Q(app_scope=GuideVideo.AppScope.BOTH))
        return qs.order_by("order", "id")


@extend_schema(exclude=True)
class GuideVideoAdminViewSet(viewsets.ModelViewSet):
    """Admin — video qo'llanmalar to'liq boshqaruvi (CRUD).

    Ro'yxat `?include_translations=1` bilan 3 tilli dict qaytaradi (form uchun).
    """

    serializer_class = GuideVideoSerializer
    permission_classes = [IsSuperOrSimpleAdmin]
    queryset = GuideVideo.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return GuideVideo.objects.none()
        return GuideVideo.objects.all().order_by("order", "id")
