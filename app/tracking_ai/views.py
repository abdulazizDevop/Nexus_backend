"""Tracking AI view'lari.

Kirish modeli:
  - bemor o'z hisobotlarini ko'radi (patient scope);
  - shifokor ACCEPTED bemorining hisobotlarini ko'radi (doctor scope);
  - oila a'zosi ACCEPTED bog'langan bemor hisobotlarini ko'radi (patient scope).
"""

import logging

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.i18n import get_request_lang
from core.permissions import get_request_role

from .models import AITrackingReport
from .serializers import AITrackingReportSerializer
from .tasks import generate_one_tracking

logger = logging.getLogger("mediik.tracking_ai")


def _can_view_patient_reports(user, role, patient_id) -> bool:
    """Shifokor (ACCEPTED) yoki oila a'zosi (ACCEPTED) — bemor hisobotiga ruxsat."""
    if role == "doctor":
        try:
            from app.doctors.models import DoctorPatient

            profile = getattr(user, "doctor_profile", None)
            if not profile:
                return False
            return DoctorPatient.objects.filter(
                doctor=profile,
                patient_id=patient_id,
                status=DoctorPatient.Status.ACCEPTED,
            ).exists()
        except ImportError:
            return False
    try:
        from app.family.models import member_can_access_patient

        return member_can_access_patient(user, patient_id)
    except ImportError:
        return False


@extend_schema(tags=["Tracking AI"])
class AITrackingReportViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Bemorning o'z AI kuzatuv hisobotlari + on-demand yaratish."""

    permission_classes = [IsAuthenticated]
    serializer_class = AITrackingReportSerializer
    queryset = AITrackingReport.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AITrackingReport.objects.none()
        return AITrackingReport.objects.filter(patient=self.request.user)

    @extend_schema(summary="Bugungi (oxirgi) hisobot")
    @action(detail=False, methods=["get"])
    def latest(self, request):
        report = self.get_queryset().order_by("-period_start").first()
        if not report:
            return Response(
                {"detail": "Hozircha hisobot yo'q."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(AITrackingReportSerializer(report).data)

    @extend_schema(summary="Hisobotni o'qilgan deb belgilash")
    @action(detail=True, methods=["post"])
    def seen(self, request, pk=None):
        report = self.get_queryset().filter(pk=pk).first()
        if not report:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not report.seen_at:
            report.seen_at = timezone.now()
            report.save(update_fields=["seen_at"])
        return Response(AITrackingReportSerializer(report).data)

    @extend_schema(summary="Hisobotni hozir yaratish (on-demand, bugungi kun)")
    @action(detail=False, methods=["post"])
    def generate(self, request):
        # Sinxron ishga tushiramiz (force=True) — demo/on-demand oqim.
        result = generate_one_tracking.apply(
            kwargs={
                "patient_id": request.user.id,
                "period_date": timezone.localdate().isoformat(),
                "force": True,
                "language": get_request_lang(request),
            }
        ).get()
        if "error" in result:
            return Response(
                {"detail": f"Hisobot yaratilmadi: {result['error']}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if "skipped" in result:
            return Response(
                {"detail": f"Hisobot yaratilmadi: {result['skipped']}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report = AITrackingReport.objects.filter(id=result["report_id"]).first()
        return Response(AITrackingReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Bemor hisobotlari (shifokor yoki oila a'zosi uchun)",
        parameters=[OpenApiParameter("patient_id", int, required=True)],
    )
    @action(detail=False, methods=["get"], url_path="by-patient/(?P<patient_id>[0-9]+)")
    def by_patient(self, request, patient_id=None):
        role = get_request_role(request)
        if int(patient_id) == request.user.id:
            qs = self.get_queryset()
        elif _can_view_patient_reports(request.user, role, patient_id):
            qs = AITrackingReport.objects.filter(patient_id=patient_id)
        else:
            return Response(
                {"detail": "Bu bemor hisobotlariga ruxsatingiz yo'q."},
                status=status.HTTP_403_FORBIDDEN,
            )
        page = self.paginate_queryset(qs)
        ser = AITrackingReportSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)
