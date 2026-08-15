import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsSuperOrSimpleAdmin

from .models import MobileAppInfo
from .serializers import MobileAppInfoSerializer

logger = logging.getLogger(__name__)


@extend_schema(tags=["Info - Mobil ilova"])
class MobileInfoView(APIView):
    """Mobil — versiya/yangilanish ma'lumoti. Login SHART EMAS (AllowAny).

    GET /info/mobile/             → {"patient": {...}, "doctor": {...}}
    GET /info/mobile/?app=patient → faqat patient obyekti
    `?lang=` (yoki Accept-Language) bo'yicha title/message tili tanlanadi.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Mobil ilova versiya/yangilanish ma'lumoti",
        parameters=[
            OpenApiParameter(
                "app", str, description="patient | doctor (bo'sh = ikkalasi)"
            ),
        ],
    )
    def get(self, request):
        ctx = {"request": request}
        app = request.query_params.get("app")
        qs = MobileAppInfo.objects.all()

        if app in (MobileAppInfo.AppScope.PATIENT, MobileAppInfo.AppScope.DOCTOR):
            obj = qs.filter(app_scope=app).first()
            if not obj:
                return Response({})
            return Response(MobileAppInfoSerializer(obj, context=ctx).data)

        return Response(
            {obj.app_scope: MobileAppInfoSerializer(obj, context=ctx).data for obj in qs}
        )


@extend_schema(exclude=True)
class MobileAppInfoAdminViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Admin — mobil versiya/yangilanish konfiguratsiyasi (2 qator: patient/doctor).

    Faqat list/retrieve/update — qatorlar migration'da seed qilinadi (create/delete yo'q).
    `?include_translations=1` bilan 3 tilli dict qaytaradi (form uchun).
    """

    serializer_class = MobileAppInfoSerializer
    permission_classes = [IsSuperOrSimpleAdmin]
    queryset = MobileAppInfo.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MobileAppInfo.objects.none()
        return MobileAppInfo.objects.all()
