from datetime import timedelta

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..models import DailySituationCheckup
from ..serializers import DailySituationCheckupSerializer


@extend_schema(tags=["Patient - Kunlik holat"])
class DailySituationCheckupViewSet(viewsets.ModelViewSet):
    """Kunlik holat nazorati — patient o'zi uchun"""

    queryset = DailySituationCheckup.objects.none()
    serializer_class = DailySituationCheckupSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "put", "head"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DailySituationCheckup.objects.none()
        return DailySituationCheckup.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    # Swagger dan yashirilgan
    @extend_schema(exclude=True)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Kunlik holat kiritish",
        description="Bugungi holatni kiritadi. Agar bugun allaqachon kiritilgan bo'lsa yangilaydi.",
    )
    def create(self, request, *args, **kwargs):
        today = timezone.localdate()
        existing = DailySituationCheckup.objects.filter(
            user=request.user, date=today
        ).first()

        if existing:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Bugungi holatni ko'rish",
        description="Bugun kiritilgan bo'lsa qaytaradi, bo'lmasa 204.",
    )
    @action(detail=False, methods=["get"], url_path="today-me")
    def today_me(self, request):
        checkup = DailySituationCheckup.objects.filter(
            user=request.user, date=timezone.localdate()
        ).first()

        if not checkup:
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(self.get_serializer(checkup).data)

    @extend_schema(
        summary="Kunlik holat tarixi (sanaga ko'ra filter)",
        description="?from=2026-03-01&to=2026-04-08 — default oxirgi 30 kun.",
    )
    @action(detail=False, methods=["get"], url_path="history")
    def history(self, request):
        qs = DailySituationCheckup.objects.filter(user=request.user)

        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")

        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)

        if not date_from and not date_to:
            qs = qs.filter(date__gte=timezone.localdate() - timedelta(days=30))

        return Response(self.get_serializer(qs.order_by("-date"), many=True).data)

    @extend_schema(
        summary="Bugungi holatni yangilash",
        description="Faqat bugungi kiritilgan holatni o'zgartirish mumkin.",
    )
    @action(detail=False, methods=["put"], url_path="today-me/update")
    def today_me_update(self, request):
        checkup = DailySituationCheckup.objects.filter(
            user=request.user, date=timezone.localdate()
        ).first()

        if not checkup:
            return Response(
                {"detail": "Bugun hali holat kiritilmagan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(checkup, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
