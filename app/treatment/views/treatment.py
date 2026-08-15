from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _destroy_with_archived_logs, _today_logs_prefetch  # underscore helper (star bermaydi)

@extend_schema(tags=["Patient - Muolajalar"])
class TreatmentViewSet(viewsets.ModelViewSet):
    """Muolajalar — dori, mashq, parhez, suv, uyqu"""

    queryset = Treatment.objects.none()
    serializer_class = TreatmentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "put", "delete", "head"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Treatment.objects.none()
        return Treatment.objects.filter(user=self.request.user).prefetch_related(
            _today_logs_prefetch()
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @extend_schema(summary="Muolajalar ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Muolaja qo'shish")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(summary="Muolajani yangilash")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Muolajani o'chirish",
        description=(
            "Butun muolajani o'chiradi. COMPLETED loglar tarix uchun saqlanadi, "
            "SKIPPED loglar bilan birga muolajaning o'zi o'chadi."
        ),
    )
    def destroy(self, request, *args, **kwargs):
        _destroy_with_archived_logs(self.get_object())
        return Response(status=204)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=TreatmentMarkSerializer,
        responses=TreatmentLogSerializer,
        summary="Muolajani bajarildi/o'tkazildi deb belgilash",
        description=(
            "Muolajani completed yoki skipped deb belgilaydi. date berilmasa — bugun. "
            "O'tmishdagi sanalarga ruxsat berilmaydi. PRN (is_as_needed) dori — kuniga "
            "bir necha marta loglanadi; rejali dori — kuniga bitta (mavjudini yangilaydi). "
            "taken_at ixtiyoriy (berilmasa now())."
        ),
    )
    @action(detail=True, methods=["post"], url_path="mark")
    def mark(self, request, pk=None):
        treatment = self.get_object()
        serializer = TreatmentMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        today = timezone.localdate()
        target_date = serializer.validated_data.get("date") or today
        if target_date < today:
            return Response(
                {"date": "O'tmishdagi sanaga belgilash mumkin emas."},
                status=400,
            )

        new_status = serializer.validated_data["status"]
        taken_at = serializer.validated_data.get("taken_at")
        completed_at = (
            (taken_at or timezone.now())
            if new_status == TreatmentLog.Status.COMPLETED
            else None
        )

        scheduled_for = serializer.validated_data.get("scheduled_for")

        if treatment.is_as_needed:
            # PRN — kuniga bir necha marta: har gal YANGI log (scheduled_for=null).
            log = TreatmentLog.objects.create(
                treatment=treatment,
                date=target_date,
                status=new_status,
                completed_at=completed_at,
            )
        elif scheduled_for is not None:
            # Per-slot rejali — (treatment, scheduled_for) idempotent (kuniga ko'p slot,
            # har slotга bittadan). Slot sanasi scheduled_for'ning local sanasi.
            slot_date = timezone.localtime(scheduled_for).date()
            if slot_date < today:
                return Response(
                    {"scheduled_for": "O'tmishdagi slotga belgilash mumkin emas."},
                    status=400,
                )
            log, _ = TreatmentLog.objects.update_or_create(
                treatment=treatment,
                scheduled_for=scheduled_for,
                defaults={
                    "date": slot_date,
                    "status": new_status,
                    "completed_at": completed_at,
                },
            )
        else:
            # Legacy rejali (scheduled_for'siz) — kuniga bitta (eski semantika).
            log, _ = TreatmentLog.objects.update_or_create(
                treatment=treatment,
                date=target_date,
                scheduled_for__isnull=True,
                defaults={"status": new_status, "completed_at": completed_at},
            )

        return Response(TreatmentLogSerializer(log).data)

    @extend_schema(
        responses=TreatmentStatsSerializer,
        summary="Oylik statistika",
        description="Joriy oy uchun bajarildi/o'tkazildi statistikasi va ketma-ket kunlar.",
    )
    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        """Bemorning oylik statistikasi: bajarilgan / rejalashtirilgan slotlar + streak."""
        return Response(compute_treatment_stats(request.user))

@extend_schema(tags=["Patient - Tarix va Bugun"])
class TreatmentLogViewSet(viewsets.ModelViewSet):
    """Muolaja loglari — kunlik bajarilish tarixi"""

    queryset = TreatmentLog.objects.none()
    serializer_class = TreatmentLogSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "head"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TreatmentLog.objects.none()
        qs = TreatmentLog.objects.filter(user=self.request.user).select_related(
            "treatment"
        )
        date = self.request.query_params.get("date")
        if date:
            qs = qs.filter(date=date)
        return qs

    @extend_schema(
        summary="Muolaja loglari",
        description="?date=2026-03-26 bilan sanaga filtrlash mumkin.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        summary="Bugungi muolajalar holati",
        description="Barcha aktiv muolajalar + bugungi log holati.",
    )
    @action(detail=False, methods=["get"], url_path="today-me")
    def today_me(self, request):
        treatments = Treatment.objects.filter(
            user=request.user, status=Treatment.Status.ACTIVE
        ).prefetch_related(_today_logs_prefetch())

        result = []
        for t in treatments:
            log = t.today_logs[0] if t.today_logs else None
            result.append(
                {
                    "treatment": TreatmentSerializer(t).data,
                    "log": TreatmentLogSerializer(log).data if log else None,
                    "is_done": log is not None,
                }
            )

        return Response(result)


# --- Doctor tomonidan ---
