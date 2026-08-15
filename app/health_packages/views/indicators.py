from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsDoctor, IsVerifiedDoctor

from ..models import HealthIndicator
from ..serializers import HealthIndicatorSerializer
from .common import _doctor_can_access_patient, _group_by_date


@extend_schema(tags=["Patient - Ko'rsatkichlar (Salomatlik)"])
class HealthIndicatorViewSet(viewsets.ModelViewSet):
    """Salomatlik ko'rsatkichlari — patient har kuni kiritib boradi"""

    queryset = HealthIndicator.objects.none()
    serializer_class = HealthIndicatorSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "put", "delete", "head"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return HealthIndicator.objects.none()
        qs = HealthIndicator.objects.filter(user=self.request.user).select_related(
            "indicator_type"
        )
        date = self.request.query_params.get("date")
        if date:
            qs = qs.filter(date=date)
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def get_permissions(self):
        # Doctor-only by-patient endpointlar — scope (JWT) bo'yicha IsDoctor.
        # _doctor_can_access_patient ACCEPTED bog'lanishni qo'shimcha tekshiradi.
        if self.action in ("by_patient", "by_patient_today"):
            return [IsVerifiedDoctor()]
        return [IsAuthenticated()]

    @extend_schema(
        summary="Ko'rsatkichlar ro'yxati (date bo'yicha guruhlangan)",
        description="?date=2026-03-26 bilan bitta kunga filtrlash mumkin.",
    )
    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_queryset(), many=True)
        return Response(_group_by_date(serializer.data))

    @extend_schema(
        summary="Ko'rsatkich qo'shish (qo'lda kiritish)",
        description=(
            "Har POST yangi event yaratadi (event sourcing). Avto-source=`manual`. "
            "Frontend `recorded_at` yubormasa hozirgi vaqt qo'yiladi. Eski yozuvni "
            "almashtirmoqchi bo'lsa, DELETE qilib yangi POST yuboring."
        ),
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        save_kwargs = {
            "user": request.user,
            "source": HealthIndicator.Source.MANUAL,
        }
        if not serializer.validated_data.get("recorded_at"):
            save_kwargs["recorded_at"] = timezone.now()
        serializer.save(**save_kwargs)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Ko'rsatkichni yangilash")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(summary="Ko'rsatkichni o'chirish")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Bugungi ko'rsatkichlar")
    @action(detail=False, methods=["get"], url_path="today-me")
    def today_me(self, request):
        indicators = self.get_queryset().filter(date=timezone.localdate())
        return Response(self.get_serializer(indicators, many=True).data)

    @extend_schema(
        summary="Bemor ko'rsatkichlari (doctor uchun)",
        description=(
            "Doctor ACCEPTED holatda bog'langan bemorining ko'rsatkichlarini "
            "ko'radi. Sana bo'yicha guruhlangan (asosiy list bilan bir xil shaklda). "
            "?date=YYYY-MM-DD bilan bitta kun, yoki ?from=&to= bilan diapazon."
        ),
        parameters=[
            OpenApiParameter("date", str, description="YYYY-MM-DD — bitta kun filtri"),
            OpenApiParameter("from", str, description="YYYY-MM-DD — diapazon boshlanishi"),
            OpenApiParameter("to", str, description="YYYY-MM-DD — diapazon tugashi"),
        ],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"by-patient/(?P<patient_id>\d+)",
    )
    def by_patient(self, request, patient_id=None):
        if not _doctor_can_access_patient(request.user, patient_id):
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = HealthIndicator.objects.filter(user_id=patient_id).select_related(
            "indicator_type"
        )
        date = request.query_params.get("date")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")

        if date:
            qs = qs.filter(date=date)
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        serializer = self.get_serializer(qs, many=True)
        return Response(_group_by_date(serializer.data))

    @extend_schema(
        summary="Bemorning bugungi ko'rsatkichlari (doctor uchun)",
        description="Doctor ACCEPTED holatda bog'langan bemorining bugungi ko'rsatkichlari.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"by-patient/(?P<patient_id>\d+)/today",
    )
    def by_patient_today(self, request, patient_id=None):
        if not _doctor_can_access_patient(request.user, patient_id):
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = HealthIndicator.objects.filter(
            user_id=patient_id, date=timezone.localdate()
        ).select_related("indicator_type")
        return Response(self.get_serializer(qs, many=True).data)
