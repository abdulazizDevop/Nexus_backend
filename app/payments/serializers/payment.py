from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class DoctorBalanceSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    held_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True,
        help_text="Hold davrida muzlatilgan summa (hali payoutga ochiq emas)",
    )
    available_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True,
        help_text="Payout uchun ochiq summa = balance - held_amount",
    )

    class Meta:
        model = DoctorBalance
        fields = [
            "id",
            "doctor",
            "doctor_name",
            "balance",
            "held_amount",
            "available_balance",
            "total_earned",
            "total_withdrawn",
            "updated_at",
        ]
        read_only_fields = fields


# --- Offline to'lov (naqd, doctor tasdiqlaydi) ---
class OfflinePaymentSerializer(serializers.ModelSerializer):
    """Offline to'lov — list/detail/javob uchun (bemor + doctor + tarif nested)."""

    doctor = serializers.SerializerMethodField()
    patient = serializers.SerializerMethodField()
    tariff = serializers.SerializerMethodField()
    purchase = serializers.SerializerMethodField()

    class Meta:
        model = OfflinePayment
        fields = [
            "id",
            "status",
            "amount",
            "doctor",
            "patient",
            "tariff",
            "purchase",
            "commission_percent",
            "commission_amount",
            "rejection_reason",
            "created_at",
            "processed_at",
        ]
        read_only_fields = fields

    def get_doctor(self, obj):
        return {
            "id": obj.doctor_id,
            "full_name": obj.doctor.user.full_name,
        }

    def get_patient(self, obj):
        # patient_name har doim qaytadi (mobil doctor ekrani uchun majburiy).
        return {
            "id": obj.patient_id,
            "full_name": obj.patient.full_name,
            "phone": obj.patient.phone,
        }

    def get_tariff(self, obj):
        if obj.tariff:
            return {
                "id": obj.tariff_id,
                "name": pick_for(self.context, obj.tariff.name),
                "duration_days": obj.tariff.duration_days,
            }
        snap = obj.tariff_snapshot or {}
        return {
            "id": obj.tariff_id,
            "name": pick_for(self.context, snap.get("name")) if snap.get("name") else "",
            "duration_days": snap.get("duration_days"),
        }

    def get_purchase(self, obj):
        if obj.purchase_id and obj.purchase:
            return {"id": obj.purchase_id, "expires_at": obj.purchase.expires_at}
        return None
class OfflinePaymentCreateSerializer(serializers.Serializer):
    """Bemor offline to'lov so'rovi yaratadi."""

    tariff_id = serializers.IntegerField()
class OfflineRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default=""
    )


# --- Balans to'ldirish (doctor) ---
class TopupRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("1")
    )
    provider = serializers.ChoiceField(choices=Payment.Provider.choices)


# --- Payment (admin uchun) ---
class PaymentAdminSerializer(serializers.ModelSerializer):
    user_phone = serializers.CharField(source="user.phone", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    provider_display = serializers.CharField(
        source="get_provider_display", read_only=True
    )
    purpose_display = serializers.CharField(
        source="get_purpose_display", read_only=True
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "user",
            "user_phone",
            "user_name",
            "amount",
            "provider",
            "provider_display",
            "provider_transaction_id",
            "status",
            "status_display",
            "purpose",
            "purpose_display",
            "metadata",
            "created_at",
            "completed_at",
        ]
        read_only_fields = fields
class InvoiceResponseSerializer(serializers.Serializer):
    """`/subscribe/` va `/purchase/` ning javobi"""

    payment_id = serializers.IntegerField()
    payment_url = serializers.URLField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    provider = serializers.CharField()
