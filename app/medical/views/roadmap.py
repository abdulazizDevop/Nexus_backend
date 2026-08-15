"""Sog'liq Navigator — yo'l xaritasi (tashxisdan keyingi qadamlar).

Oqim:
1) POST /medical/roadmap/setup/   — tashxis + qadamlar bitta so'rovda
   (avvalgi aktiv tashxis deaktiv bo'ladi);
2) GET  /medical/roadmap/active/  — aktiv tashxis + davrlar bo'yicha qadamlar
   + progress (doimiy "odat" qadamlar hisobga kirmaydi);
3) POST /medical/roadmap/steps/{id}/complete/   — qadam bajarildi
   POST /medical/roadmap/steps/{id}/uncomplete/ — belgini olib tashlash.
"""

import logging

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsPatient

from ..models import MedicalCondition, RoadmapStep
from ..serializers.roadmap import (
    RoadmapConditionSerializer,
    RoadmapSetupSerializer,
    RoadmapStepSerializer,
)

logger = logging.getLogger("mediik.medical")


def _progress(condition) -> dict:
    """Belgilanadigan (doimiy bo'lmagan) qadamlar bo'yicha progress."""
    steps = RoadmapStep.objects.filter(condition=condition)
    checkable = steps.exclude(period=RoadmapStep.Period.ONGOING)
    total = checkable.count()
    completed = checkable.filter(status=RoadmapStep.Status.COMPLETED).count()
    return {
        "completed": completed,
        "total": total,
        "percent": int(completed * 100 / total) if total else 0,
        "habits": steps.filter(period=RoadmapStep.Period.ONGOING).count(),
    }


def _roadmap_payload(condition) -> dict:
    steps = RoadmapStep.objects.filter(condition=condition)
    grouped = {p: [] for p, _ in RoadmapStep.Period.choices}
    for step in steps:
        grouped[step.period].append(RoadmapStepSerializer(step).data)
    return {
        "condition": RoadmapConditionSerializer(condition).data,
        "periods": [
            {"period": p, "period_label": label, "steps": grouped[p]}
            for p, label in RoadmapStep.Period.choices
        ],
        "progress": _progress(condition),
    }


@extend_schema(tags=["Medical - Navigator yo'l xaritasi"])
class RoadmapSetupView(APIView):
    """Tashxis + yo'l xaritasi qadamlarini bitta so'rovda o'rnatish."""

    permission_classes = [IsPatient]

    @extend_schema(
        request=RoadmapSetupSerializer,
        summary="Yo'l xaritasini o'rnatish (tashxis + qadamlar)",
        description=(
            "Avvalgi aktiv tashxis deaktiv bo'ladi (qadamlari saqlanib qoladi). "
            "Qadamlar odatda mobil ilova bazasidagi kasallik shablonidan keladi."
        ),
    )
    def post(self, request):
        ser = RoadmapSetupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cond_data = ser.validated_data["condition"]
        steps = ser.validated_data["steps"]

        with transaction.atomic():
            MedicalCondition.objects.filter(
                user=request.user, is_active=True
            ).update(is_active=False)

            condition = MedicalCondition.objects.create(
                user=request.user,
                added_by=request.user,
                type=cond_data["type"],
                name=cond_data["name"],
                icd10=cond_data["icd10"],
                plain_explanation=cond_data["plain_explanation"],
                is_active=True,
                discovered_at=timezone.localdate(),
            )
            RoadmapStep.objects.bulk_create(
                [
                    RoadmapStep(
                        condition=condition,
                        user=request.user,
                        patient_profile=condition.patient_profile,
                        period=s["period"],
                        order=s.get("order") or i,
                        title=s["title"],
                        description=s.get("description") or "",
                        specialist=s.get("specialist") or "",
                    )
                    for i, s in enumerate(steps)
                ]
            )

        return Response(_roadmap_payload(condition), status=status.HTTP_201_CREATED)


@extend_schema(tags=["Medical - Navigator yo'l xaritasi"])
class ActiveRoadmapView(APIView):
    """Aktiv tashxis + davrlar bo'yicha qadamlar + progress."""

    permission_classes = [IsPatient]

    @extend_schema(summary="Aktiv yo'l xaritasi")
    def get(self, request):
        condition = (
            MedicalCondition.objects.filter(user=request.user, is_active=True)
            .order_by("-created_at")
            .first()
        )
        if not condition:
            return Response(
                {"detail": "Aktiv tashxis yo'q. Avval roadmap/setup/ qiling."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_roadmap_payload(condition))


class _StepActionView(APIView):
    permission_classes = [IsPatient]

    def _get_step(self, request, pk):
        return RoadmapStep.objects.filter(pk=pk, user=request.user).first()


@extend_schema(tags=["Medical - Navigator yo'l xaritasi"])
class RoadmapStepCompleteView(_StepActionView):
    @extend_schema(summary="Qadamni bajarildi deb belgilash")
    def post(self, request, pk: int):
        step = self._get_step(request, pk)
        if not step:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if step.is_habit:
            return Response(
                {"detail": "Doimiy (odat) qadam bajarildi deb yopilmaydi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if step.status != RoadmapStep.Status.COMPLETED:
            step.status = RoadmapStep.Status.COMPLETED
            step.completed_at = timezone.now()
            step.save(update_fields=["status", "completed_at"])
        return Response(
            {
                "step": RoadmapStepSerializer(step).data,
                "progress": _progress(step.condition),
            }
        )


@extend_schema(tags=["Medical - Navigator yo'l xaritasi"])
class RoadmapStepUncompleteView(_StepActionView):
    @extend_schema(summary="Bajarildi belgisini olib tashlash")
    def post(self, request, pk: int):
        step = self._get_step(request, pk)
        if not step:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if step.status == RoadmapStep.Status.COMPLETED:
            step.status = RoadmapStep.Status.PENDING
            step.completed_at = None
            step.save(update_fields=["status", "completed_at"])
        return Response(
            {
                "step": RoadmapStepSerializer(step).data,
                "progress": _progress(step.condition),
            }
        )
