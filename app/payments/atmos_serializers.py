"""Atmos endpointlari uchun DRF serializerlar."""

from rest_framework import serializers

from .models import AtmosSavedCard


# ---------- Karta boshqaruvi ----------


class AtmosCardBindSerializer(serializers.Serializer):
    """POST /atmos/cards/bind/ — kirish"""

    card_number = serializers.RegexField(
        regex=r"^\d{16}$", help_text="16 raqamli karta raqami"
    )
    expiry = serializers.RegexField(
        regex=r"^\d{4}$", help_text="YYMM format, masalan 2505"
    )


class AtmosCardBindResponseSerializer(serializers.Serializer):
    """POST /atmos/cards/bind/ — chiqish"""

    atmos_tx_id = serializers.IntegerField()
    phone_masked = serializers.CharField()


class AtmosCardConfirmSerializer(serializers.Serializer):
    """POST /atmos/cards/confirm/ — kirish"""

    atmos_tx_id = serializers.IntegerField()
    otp = serializers.RegexField(regex=r"^\d{4,8}$")


class AtmosSavedCardSerializer(serializers.ModelSerializer):
    """GET /atmos/cards/ va POST /atmos/cards/confirm/ — chiqish"""

    pan_last4 = serializers.CharField(read_only=True)

    class Meta:
        model = AtmosSavedCard
        fields = [
            "id",
            "pan_masked",
            "pan_last4",
            "expiry",
            "card_holder",
            "is_primary",
            "created_at",
        ]
        read_only_fields = fields


# ---------- To'lov ----------


class AtmosPaySerializer(serializers.Serializer):
    """POST /atmos/pay/ — kirish"""

    PURPOSE_CHOICES = [
        ("pro_subscription", "Pro obuna"),
        ("doctor_tariff", "Doctor tarifi"),
    ]

    saved_card_id = serializers.IntegerField()
    purpose = serializers.ChoiceField(choices=PURPOSE_CHOICES)
    plan_id = serializers.IntegerField(required=False, allow_null=True)
    tariff_id = serializers.IntegerField(required=False, allow_null=True)
    doctor_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        purpose = attrs["purpose"]
        if purpose == "pro_subscription" and not attrs.get("plan_id"):
            raise serializers.ValidationError(
                {"plan_id": "Pro obuna uchun plan_id majburiy."}
            )
        if purpose == "doctor_tariff":
            if not attrs.get("tariff_id"):
                raise serializers.ValidationError(
                    {"tariff_id": "Doctor tarifi uchun tariff_id majburiy."}
                )
            if not attrs.get("doctor_id"):
                raise serializers.ValidationError(
                    {"doctor_id": "Doctor tarifi uchun doctor_id majburiy."}
                )
        return attrs


class AtmosPayResponseSerializer(serializers.Serializer):
    """POST /atmos/pay/ — chiqish"""

    payment_id = serializers.IntegerField()
    otp_required = serializers.BooleanField()


class AtmosConfirmSerializer(serializers.Serializer):
    """POST /atmos/pay/confirm/ — kirish"""

    payment_id = serializers.IntegerField()
    otp = serializers.RegexField(regex=r"^\d{4,8}$")


class AtmosConfirmResponseSerializer(serializers.Serializer):
    """POST /atmos/pay/confirm/ — chiqish"""

    status = serializers.CharField()
    ofd_url = serializers.CharField(required=False, allow_blank=True)
