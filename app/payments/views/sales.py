from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


@extend_schema(tags=["Payments - Doctor"])
class DoctorSalesView(APIView):
    """Doctor tariflari bo'yicha savdo tarixi"""

    permission_classes = [IsVerifiedDoctor]
    serializer_class = DoctorTariffPurchaseSerializer

    @extend_schema(
        summary="Mening savdolarim",
        responses=DoctorTariffPurchaseSerializer(many=True),
    )
    def get(self, request):
        profile = getattr(request.user, "doctor_profile", None)
        if not profile:
            return Response([])
        sales = DoctorTariffPurchase.objects.filter(doctor=profile).select_related(
            "patient", "tariff", "doctor__user"
        )
        return Response(DoctorTariffPurchaseSerializer(sales, many=True).data)


@extend_schema(tags=["Payments - Doctor"])
class DoctorSalesStatsView(APIView):
    """Doctor savdo dashboard'i — KPI + tarif breakdown.

    Oxirgi savdolar ro'yxati alohida `/doctor/sales/` endpoint'ida.
    """

    permission_classes = [IsVerifiedDoctor]
    serializer_class = DoctorSalesStatsSerializer

    PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90}
    DEFAULT_PERIOD = "30d"

    @extend_schema(
        summary="Mening savdolarim — statistika (dashboard)",
        parameters=[
            OpenApiParameter(
                name="period",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Davr filtri (default: 30d)",
                required=False,
                enum=["7d", "30d", "90d", "all"],
            ),
        ],
        responses=DoctorSalesStatsSerializer,
    )
    def get(self, request):
        now = timezone.now()
        period = request.query_params.get("period", self.DEFAULT_PERIOD)
        if period not in self.PERIOD_DAYS and period != "all":
            period = self.DEFAULT_PERIOD

        period_from = (
            now - timezone.timedelta(days=self.PERIOD_DAYS[period])
            if period in self.PERIOD_DAYS
            else None
        )

        profile = getattr(request.user, "doctor_profile", None)
        if not profile:
            return Response(self._empty_response(period, period_from, now))

        base_qs = DoctorTariffPurchase.objects.filter(doctor=profile)
        period_qs = base_qs if period_from is None else base_qs.filter(
            created_at__gte=period_from
        )

        agg = period_qs.aggregate(
            total_revenue=Sum("doctor_earnings"),
            sales_count=Count("id"),
        )
        total_revenue = agg["total_revenue"] or Decimal("0")
        sales_count = agg["sales_count"] or 0
        average_sale = (
            (total_revenue / sales_count) if sales_count else Decimal("0")
        )

        kpi = {
            "active_subscriptions": base_qs.filter(expires_at__gt=now).count(),
            "active_delta_week": base_qs.filter(
                created_at__gte=now - timezone.timedelta(days=7),
                expires_at__gt=now,
            ).count(),
            "renewal_rate": self._renewal_rate(base_qs, period_qs),
            "average_sale": average_sale,
            "sales_count": sales_count,
        }

        data = {
            "period": period,
            "period_from": period_from,
            "period_to": now,
            "total_revenue": total_revenue,
            "kpi": kpi,
            "by_tariff": self._by_tariff(period_qs),
        }
        return Response(DoctorSalesStatsSerializer(data).data)

    @staticmethod
    def _renewal_rate(base_qs, period_qs) -> float:
        """Period ichida 2+ marta sotib olgan unique patientlar / unique patientlar.

        Lifetime-bo'yicha hisoblanadi: agar patient period dan oldinroq ham sotib
        olgan bo'lsa, 2-savdo "takror" hisoblanadi. Shu sababli base_qs ustidan
        Count olamiz, period faqat patientlar to'plamini chegaralash uchun.
        """
        # Why set(): DoctorTariffPurchase.Meta'da `ordering = ["-created_at"]`
        # bor — `values_list().distinct()` SQL'ga ORDER BY created_at qo'shadi
        # va DISTINCT (patient_id, created_at) bo'lib dedup ishlamay qoladi.
        patient_ids = set(period_qs.values_list("patient_id", flat=True))
        if not patient_ids:
            return 0.0
        repeat_patients = (
            base_qs.filter(patient_id__in=patient_ids)
            .values("patient_id")
            .annotate(c=Count("id"))
            .filter(c__gte=2)
            .count()
        )
        return round(repeat_patients / len(patient_ids), 4)

    @staticmethod
    def _by_tariff(period_qs):
        """Tarif bo'yicha groupby. O'chirilgan tarif uchun snapshot'dan nom olinadi."""
        rows = list(
            period_qs.values("tariff_id")
            .annotate(count=Count("id"), revenue=Sum("doctor_earnings"))
            .order_by("-revenue")
        )
        tariff_ids = [r["tariff_id"] for r in rows if r["tariff_id"]]
        tariffs_map = {
            t.id: t for t in DoctorTariff.objects.filter(id__in=tariff_ids)
        }

        # O'chirilgan tariflar uchun snapshot'dan name/duration olamiz —
        # har tariff_id=None guruhi uchun bitta vakil purchase yetadi.
        snapshot_lookup = {}
        if any(r["tariff_id"] is None for r in rows):
            snap = (
                period_qs.filter(tariff_id__isnull=True)
                .values("tariff_snapshot")
                .first()
            )
            if snap:
                snapshot_lookup = snap["tariff_snapshot"] or {}

        result = []
        for r in rows:
            tariff = tariffs_map.get(r["tariff_id"])
            if tariff:
                name = tariff.name
                duration_days = tariff.duration_days
            else:
                name = snapshot_lookup.get("name") or "O'chirilgan tarif"
                duration_days = snapshot_lookup.get("duration_days")
            result.append(
                {
                    "tariff_id": r["tariff_id"],
                    "name": name,
                    "duration_days": duration_days,
                    "count": r["count"],
                    "revenue": r["revenue"] or Decimal("0"),
                }
            )
        return result

    @staticmethod
    def _empty_response(period, period_from, period_to):
        return {
            "period": period,
            "period_from": period_from,
            "period_to": period_to,
            "total_revenue": Decimal("0"),
            "kpi": {
                "active_subscriptions": 0,
                "active_delta_week": 0,
                "renewal_rate": 0.0,
                "average_sale": Decimal("0"),
                "sales_count": 0,
            },
            "by_tariff": [],
        }


# ============ Admin ============


