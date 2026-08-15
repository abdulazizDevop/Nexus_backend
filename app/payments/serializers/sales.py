from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class DoctorSalesKpiSerializer(serializers.Serializer):
    active_subscriptions = serializers.IntegerField(
        help_text="Hozirda aktiv (expires_at > now) tariflar soni"
    )
    active_delta_week = serializers.IntegerField(
        help_text="Oxirgi 7 kunda yaratilgan va hali aktiv tariflar soni"
    )
    renewal_rate = serializers.FloatField(
        help_text="Period ichida 2+ marta sotib olgan unique patientlar foizi (0..1)"
    )
    average_sale = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Period ichida bitta savdoning o'rtacha doctor_earnings qiymati",
    )
    sales_count = serializers.IntegerField(help_text="Period ichidagi savdolar soni")
class DoctorSalesByTariffSerializer(serializers.Serializer):
    tariff_id = serializers.IntegerField(
        allow_null=True, help_text="O'chirilgan tarif uchun null"
    )
    name = serializers.CharField()
    duration_days = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
class DoctorSalesStatsSerializer(serializers.Serializer):
    period = serializers.CharField(help_text="7d | 30d | 90d | all")
    period_from = serializers.DateTimeField(
        allow_null=True, help_text="period=all bo'lsa null"
    )
    period_to = serializers.DateTimeField()
    total_revenue = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Period ichidagi doctor_earnings yig'indisi (komissiyadan keyin)",
    )
    kpi = DoctorSalesKpiSerializer()
    by_tariff = DoctorSalesByTariffSerializer(many=True)


# --- Doctor payout (pul yechish) ---
