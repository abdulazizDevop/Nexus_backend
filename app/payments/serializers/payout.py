from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class DoctorPayoutCardSerializer(serializers.ModelSerializer):
    """Doctor o'z kartasi — UI mockup'ga mos response."""

    card_last4 = serializers.CharField(read_only=True)
    expiry = serializers.CharField(source="expiry_display", read_only=True)
    card_type_display = serializers.CharField(
        source="get_card_type_display", read_only=True
    )

    class Meta:
        model = DoctorPayoutCard
        fields = [
            "id",
            "card_type",
            "card_type_display",
            "card_number",
            "card_last4",
            "card_holder",
            "bank_name",
            "expiry_month",
            "expiry_year",
            "expiry",
            "is_primary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "card_type_display",
            "card_last4",
            "expiry",
            "is_primary",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "card_number": {"write_only": True},
        }

    def validate_card_number(self, value):
        digits = "".join(c for c in value if c.isdigit())
        if len(digits) != 16:
            raise serializers.ValidationError(
                "Karta raqami 16 raqamdan iborat bo'lishi kerak."
            )
        return digits

    def validate_card_holder(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Karta egasi nomi juda qisqa.")
        return value

    def validate_expiry_month(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError("Oy 1..12 oralig'ida bo'lishi kerak.")
        return value

    def validate_expiry_year(self, value):
        # 2-xonali kutamiz: 24..99 (4-xonali kelsa, oxirgi 2 raqam)
        if value >= 100:
            value = value % 100
        if not 0 <= value <= 99:
            raise serializers.ValidationError(
                "Yil 2-xonali (0..99) bo'lishi kerak."
            )
        return value
class PayoutRequestCreateSerializer(serializers.Serializer):
    """Doctor yangi payout so'rovi yaratadi — saqlangan karta id orqali."""

    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("1")
    )
    card_id = serializers.IntegerField(help_text="DoctorPayoutCard ID")
class PayoutRequestSerializer(serializers.ModelSerializer):
    """Doctor o'z so'rovlarini ko'radi."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    card_last4 = serializers.CharField(read_only=True)
    detail_status = serializers.CharField(read_only=True)
    detail_status_label = serializers.CharField(read_only=True)

    class Meta:
        model = PayoutRequest
        fields = [
            "id",
            "amount",
            "card_id",
            "card_type",
            "card_last4",
            "card_holder",
            "bank_name",
            "status",
            "status_display",
            "sub_status",
            "detail_status",
            "detail_status_label",
            "rejection_reason",
            "admin_note",
            "transaction_ref",
            "created_at",
            "processed_at",
        ]
        read_only_fields = fields
class PayoutRequestAdminSerializer(serializers.ModelSerializer):
    """Admin payout so'rovlarini ko'radi (to'liq karta raqami bilan)."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    sub_status_display = serializers.CharField(
        source="get_sub_status_display", read_only=True
    )
    detail_status = serializers.CharField(read_only=True)
    detail_status_label = serializers.CharField(read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    doctor_phone = serializers.CharField(source="doctor.user.phone", read_only=True)
    doctor_balance = serializers.SerializerMethodField()
    processed_by_phone = serializers.CharField(
        source="processed_by.phone", read_only=True, default=None
    )

    class Meta:
        model = PayoutRequest
        fields = [
            "id",
            "doctor",
            "doctor_name",
            "doctor_phone",
            "doctor_balance",
            "amount",
            "card_id",
            "card_type",
            "card_number",
            "card_holder",
            "bank_name",
            "status",
            "status_display",
            "sub_status",
            "sub_status_display",
            "detail_status",
            "detail_status_label",
            "admin_note",
            "rejection_reason",
            "transaction_ref",
            "processed_by",
            "processed_by_phone",
            "method",
            "atmos_asl_state",
            "atmos_asl_transaction_id",
            "atmos_asl_ext_id",
            "atmos_asl_error",
            "atmos_asl_poll_count",
            "created_at",
            "processed_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2))
    def get_doctor_balance(self, obj):
        balance = getattr(obj.doctor, "balance", None)
        return str(balance.balance) if balance else "0"


# --- Wallet (doctor) ---
class PayoutStatsSerializer(serializers.Serializer):
    total_withdrawn = serializers.DecimalField(max_digits=14, decimal_places=2)
    in_progress_total = serializers.DecimalField(max_digits=14, decimal_places=2)
class PayoutFilterCountsSerializer(serializers.Serializer):
    all = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    completed = serializers.IntegerField()
    rejected = serializers.IntegerField()
class PayoutListResponseSerializer(serializers.Serializer):
    stats = PayoutStatsSerializer()
    filter_counts = PayoutFilterCountsSerializer()
    results = PayoutRequestSerializer(many=True)
