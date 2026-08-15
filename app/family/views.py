"""Oila a'zosi kuzatuvi view'lari.

Ikkala tomon ham PATIENT scope'da ishlaydi (a'zo ham oddiy foydalanuvchi,
patient app'dan kiradi):
  - bemor tomoni: a'zolar ro'yxati, taklif, bekor qilish;
  - a'zo tomoni: takliflar, qabul/rad, kuzatilayotgan bemorlar, kunlik hisobot.
"""

import logging
from datetime import date as date_cls

from django.contrib.auth import get_user_model
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.auth.serializers.common import normalize_phone
from app.notifications.models import Notification
from app.notifications.utils import notify
from core.permissions import IsPatient

from .models import FamilyLink, member_can_access_patient
from .serializers import (
    FamilyInvitationSerializer,
    FamilyInviteInputSerializer,
    FamilyMemberSerializer,
)

logger = logging.getLogger("mediik.family")
User = get_user_model()


@extend_schema(tags=["Family - Bemor (a'zolarim)"])
class FamilyLinkViewSet(viewsets.GenericViewSet):
    """Bemor tomoni: oila a'zolarini boshqarish."""

    permission_classes = [IsPatient]
    serializer_class = FamilyMemberSerializer
    queryset = FamilyLink.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FamilyLink.objects.none()
        return FamilyLink.objects.filter(patient=self.request.user).select_related("member")

    @extend_schema(summary="Mening oila a'zolarim ro'yxati")
    def list(self, request):
        rows = self.get_queryset().exclude(status=FamilyLink.Status.REVOKED)
        return Response(FamilyMemberSerializer(rows, many=True).data)

    @extend_schema(
        summary="Oila a'zosini taklif qilish (telefon raqami bo'yicha)",
        request=FamilyInviteInputSerializer,
    )
    @action(detail=False, methods=["post"])
    def invite(self, request):
        ser = FamilyInviteInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = normalize_phone(ser.validated_data["phone"])
        relation = ser.validated_data["relation"]

        member = User.objects.filter(phone=phone).first()
        if not member:
            return Response(
                {"detail": "Bu raqamda foydalanuvchi topilmadi. A'zo avval ilovada ro'yxatdan o'tsin."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if member.id == request.user.id:
            return Response(
                {"detail": "O'zingizni oila a'zosi sifatida qo'sha olmaysiz."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Unique (patient, member) — mavjud bo'lsa upsert (rad/bekor → qayta pending).
        link, created = FamilyLink.objects.get_or_create(
            patient=request.user,
            member=member,
            defaults={"relation": relation},
        )
        if not created:
            if link.status == FamilyLink.Status.ACCEPTED:
                return Response(
                    {"detail": "Bu a'zo allaqachon sizni kuzatmoqda."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            link.relation = relation
            link.status = FamilyLink.Status.PENDING
            link.responded_at = None
            link.save(update_fields=["relation", "status", "responded_at"])

        try:
            notify(
                member,
                type=Notification.Type.FAMILY_INVITE,
                title="Oila a'zosi taklifi",
                body=f"{request.user.full_name} sizni o'z sog'lig'ini kuzatishga taklif qildi.",
                data={"kind": "family_invite", "link_id": link.id},
                app_scope="patient",
            )
        except Exception:
            logger.exception("Family invite push xatosi link=%s", link.id)

        return Response(
            FamilyMemberSerializer(link).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(summary="A'zoni kuzatuvdan chiqarish (bekor qilish)")
    def destroy(self, request, pk=None):
        link = self.get_queryset().filter(pk=pk).first()
        if not link:
            return Response(status=status.HTTP_404_NOT_FOUND)
        link.mark_responded(FamilyLink.Status.REVOKED)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["Family - A'zo (kuzatuvchi)"])
class FamilyMemberSideViewSet(viewsets.GenericViewSet):
    """A'zo tomoni: takliflar va kuzatilayotgan bemorlar."""

    permission_classes = [IsPatient]
    serializer_class = FamilyInvitationSerializer
    queryset = FamilyLink.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FamilyLink.objects.none()
        return FamilyLink.objects.filter(member=self.request.user).select_related(
            "patient", "patient_profile"
        )

    @extend_schema(summary="Menga kelgan takliflar (pending)")
    @action(detail=False, methods=["get"])
    def invitations(self, request):
        rows = self.get_queryset().filter(status=FamilyLink.Status.PENDING)
        return Response(FamilyInvitationSerializer(rows, many=True).data)

    def _respond(self, request, pk, new_status, notif_type, notif_title, notif_body):
        link = self.get_queryset().filter(
            pk=pk, status=FamilyLink.Status.PENDING
        ).first()
        if not link:
            return Response(
                {"detail": "Taklif topilmadi yoki allaqachon javob berilgan."},
                status=status.HTTP_404_NOT_FOUND,
            )
        link.mark_responded(new_status)
        try:
            notify(
                link.patient,
                type=notif_type,
                title=notif_title,
                body=notif_body.format(name=request.user.full_name),
                data={"kind": "family_response", "link_id": link.id},
                app_scope="patient",
            )
        except Exception:
            logger.exception("Family javob push xatosi link=%s", link.id)
        return Response(FamilyInvitationSerializer(link).data)

    @extend_schema(summary="Taklifni qabul qilish")
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._respond(
            request, pk, FamilyLink.Status.ACCEPTED,
            Notification.Type.FAMILY_ACCEPTED,
            "Taklif qabul qilindi",
            "{name} endi sog'lig'ingizni kuzatib boradi.",
        )

    @extend_schema(summary="Taklifni rad etish")
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return self._respond(
            request, pk, FamilyLink.Status.DECLINED,
            Notification.Type.FAMILY_DECLINED,
            "Taklif rad etildi",
            "{name} taklifingizni rad etdi.",
        )

    @extend_schema(summary="Men kuzatayotgan bemorlar")
    @action(detail=False, methods=["get"])
    def patients(self, request):
        rows = self.get_queryset().filter(status=FamilyLink.Status.ACCEPTED)
        return Response(FamilyInvitationSerializer(rows, many=True).data)


@extend_schema(tags=["Family - A'zo (kuzatuvchi)"])
class FamilyDailyReportView(APIView):
    """A'zo uchun bemorning kunlik kuzatuv hisoboti (FAQAT O'QISH).

    Tarkib: kayfiyat (checkup), ko'rsatkichlar, muolaja bajarilishi va oxirgi
    AI kuzatuv hisoboti. Shifokor daily_report'ining soddalashtirilgan nusxasi.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Bemorning kunlik hisoboti (oila a'zosi uchun)",
        parameters=[OpenApiParameter("date", str, description="YYYY-MM-DD (default: bugun)")],
    )
    def get(self, request, patient_id: int):
        if not member_can_access_patient(request.user, patient_id):
            return Response(
                {"detail": "Bu bemorni kuzatishga ruxsatingiz yo'q."},
                status=status.HTTP_403_FORBIDDEN,
            )
        patient = User.objects.filter(id=patient_id).first()
        if not patient:
            return Response(status=status.HTTP_404_NOT_FOUND)

        raw_date = request.query_params.get("date")
        try:
            target_date = (
                date_cls.fromisoformat(raw_date) if raw_date else timezone.localdate()
            )
        except ValueError:
            return Response(
                {"detail": "date formati noto'g'ri (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lazy importlar — app yuklanish tartibiga bog'lanmaslik uchun.
        from app.health_packages.models import DailySituationCheckup, HealthIndicator
        from app.health_packages.serializers import (
            DailySituationCheckupSerializer,
            HealthIndicatorSerializer,
        )
        from app.treatment.models import Treatment, TreatmentLog

        checkup = DailySituationCheckup.objects.filter(
            user=patient, date=target_date
        ).first()
        indicators = HealthIndicator.objects.filter(
            user=patient, date=target_date
        ).select_related("indicator_type").order_by("recorded_at")

        treatments_data = []
        total_slots = 0
        completed_slots = 0
        active = Treatment.objects.filter(user=patient, status=Treatment.Status.ACTIVE)
        logs = TreatmentLog.objects.filter(user=patient, date=target_date)
        logs_by_treatment: dict[int, int] = {}
        for log in logs.filter(status=TreatmentLog.Status.COMPLETED):
            if log.treatment_id:
                logs_by_treatment[log.treatment_id] = (
                    logs_by_treatment.get(log.treatment_id, 0) + 1
                )
        for t in active:
            if not t._scheduled_on(target_date):
                continue
            slots = t.slots_per_day() or 1
            done = min(logs_by_treatment.get(t.id, 0), slots)
            total_slots += slots
            completed_slots += done
            treatments_data.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "type": t.type,
                    "completed": done,
                    "total": slots,
                }
            )

        ai_report = None
        try:
            from app.tracking_ai.models import AITrackingReport
            from app.tracking_ai.serializers import AITrackingReportSerializer

            latest = (
                AITrackingReport.objects.filter(patient=patient)
                .order_by("-period_start")
                .first()
            )
            if latest:
                ai_report = AITrackingReportSerializer(latest).data
        except ImportError:
            pass

        return Response(
            {
                "date": target_date.isoformat(),
                "patient_id": patient.id,
                "patient_name": patient.full_name,
                "checkup": DailySituationCheckupSerializer(checkup).data if checkup else None,
                "indicators": HealthIndicatorSerializer(
                    indicators, many=True, context={"request": request}
                ).data,
                "treatments": treatments_data,
                "completion_percent": (
                    int(completed_slots * 100 / total_slots) if total_slots else None
                ),
                "ai_report": ai_report,
            }
        )
