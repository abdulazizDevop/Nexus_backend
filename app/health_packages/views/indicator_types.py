from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsSuperOrSimpleAdmin

from ..models import HealthIndicator, HealthIndicatorType
from ..serializers import HealthIndicatorTypeSerializer


@extend_schema(tags=["Patient - Ko'rsatkich turlari (Salomatlik)"])
class HealthIndicatorTypeViewSet(viewsets.ModelViewSet):
    """Ko'rsatkich turlari — patient/doctor o'qiydi, admin to'liq boshqaradi.

    BARCHA rollar BARCHA turlarni oladi (filtr yo'q). UI turning joyini `category`
    (manual/diet) va `manual_entry` flag'lari bo'yicha hal qiladi — kodда
    nom/system_key taxmini emas. Admin POST/PUT'da `category`, `manual_entry`,
    `system_key` belgilay oladi. Bemor o'lchovi mavjud turни o'chirib bo'lmaydi.
    """

    queryset = HealthIndicatorType.objects.none()
    serializer_class = HealthIndicatorTypeSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HealthIndicatorType.objects.none()
        # Barcha rollar (patient/doctor/admin) BARCHA turlarni ko'radi —
        # system_key bor (Diet AI macros) va null (oddiy) turlar birga.
        # Cheklov yo'q.
        return HealthIndicatorType.objects.all()

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsSuperOrSimpleAdmin()]

    @extend_schema(summary="Ko'rsatkich turlarini ko'rish")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if HealthIndicator.objects.filter(indicator_type=instance).exists():
            return Response(
                {
                    "detail": (
                        "Bu ko'rsatkich turi bemor o'lchovlarida ishlatilgan — "
                        "o'chirish mumkin emas. Yangi turi qo'shing yoki avval o'lchovlarni o'chiring."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)
