from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class DoctorTariffSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Doctor o'zi ko'radi va tahrirlaydi.

    Translatable maydonlar: `name`, `description`, `features`, `discount_label`.
    Doctor form'i: `?include_translations=1` bilan to'liq dict yuklab oladi va
    saqlaganda 3 til to'ldirilgan dict yuboradi (auto-tarjima tugmasi orqali).
    """

    translatable_fields = ["name", "description", "features", "discount_label"]
    final_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = DoctorTariff
        fields = [
            "id",
            "name",
            "description",
            "price",
            "duration_days",
            "features",
            "discount_enabled",
            "discount_type",
            "discount_value",
            "discount_target",
            "discount_expires_at",
            "discount_label",
            "final_price",
            "status",
            "status_display",
            "rejection_reason",
            "is_active",
            "is_popular",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "rejection_reason",
            "final_price",
            "created_at",
            "updated_at",
        ]

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Narx 0 dan katta bo'lishi kerak.")
        return value

    def validate_duration_days(self, value):
        if value <= 0:
            raise serializers.ValidationError("Muddat 0 dan katta bo'lishi kerak.")
        return value

    def validate(self, attrs):
        discount_enabled = attrs.get("discount_enabled", False)
        if discount_enabled:
            dtype = attrs.get("discount_type") or DoctorTariff.DiscountType.PERCENT
            dvalue = attrs.get("discount_value") or Decimal("0")
            if dvalue <= 0:
                raise serializers.ValidationError(
                    {"discount_value": "Chegirma qiymati 0 dan katta bo'lishi kerak."}
                )
            if dtype == DoctorTariff.DiscountType.PERCENT and dvalue > 100:
                raise serializers.ValidationError(
                    {"discount_value": "Foiz 100 dan oshmasligi kerak."}
                )
            price = attrs.get("price") or (self.instance.price if self.instance else 0)
            if dtype == DoctorTariff.DiscountType.AMOUNT and dvalue >= price:
                raise serializers.ValidationError(
                    {
                        "discount_value": "Chegirma summasi narxdan kichik bo'lishi kerak."
                    }
                )
        return attrs
class DoctorTariffPublicSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Patient uchun — approved + active tariflar. Til so'rov tilida."""

    translatable_fields = ["name", "description", "features", "discount_label"]
    doctor_id = serializers.IntegerField(source="doctor.id", read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    final_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    price_for_me = serializers.SerializerMethodField()

    class Meta:
        model = DoctorTariff
        fields = [
            "id",
            "doctor_id",
            "doctor_name",
            "name",
            "description",
            "price",
            "final_price",
            "price_for_me",
            "duration_days",
            "features",
            "discount_enabled",
            "discount_type",
            "discount_value",
            "discount_target",
            "discount_expires_at",
            "discount_label",
            "is_popular",
        ]

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=2))
    def get_price_for_me(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return str(obj.get_price_for(request.user))
        return str(obj.price)
class DoctorTariffAdminSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Admin moderatsiya uchun — `?include_translations=1` bilan 3 til ko'rinadi."""

    translatable_fields = ["name", "description", "features", "discount_label"]
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    doctor_phone = serializers.CharField(source="doctor.user.phone", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    final_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = DoctorTariff
        fields = [
            "id",
            "doctor",
            "doctor_name",
            "doctor_phone",
            "name",
            "description",
            "price",
            "duration_days",
            "features",
            # Chegirma (aksiya) maydonlari — admin moderatsiyada ko'rinishi uchun.
            # Frontend (DoctorTariffModeration) bularni allaqachon render qiladi.
            "discount_enabled",
            "discount_type",
            "discount_value",
            "discount_target",
            "discount_expires_at",
            "discount_label",
            "final_price",
            "status",
            "status_display",
            "rejection_reason",
            "is_active",
            "is_popular",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
class RejectTariffSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)
class PurchaseRequestSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=Payment.Provider.choices)
class DoctorTariffPurchaseSerializer(serializers.ModelSerializer): # tariff.name JSONField, oldin CharField raw dict qaytarardi.
    tariff_name = serializers.SerializerMethodField()
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    is_active = serializers.BooleanField(read_only=True) # Patient profile ID
    patient_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DoctorTariffPurchase
        fields = [
            "id",
            "patient",
            "patient_name",
            "patient_profile_id",
            "tariff",
            "tariff_name",
            "doctor",
            "doctor_name",
            "tariff_snapshot",
            "starts_at",
            "expires_at",
            "amount_paid",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields

    def get_tariff_name(self, obj):
        if not obj.tariff:
            # Tarif o'chirilgan bo'lsa snapshot'dan
            snapshot_name = (obj.tariff_snapshot or {}).get("name")
            return pick_for(self.context, snapshot_name) if snapshot_name else ""
        return pick_for(self.context, obj.tariff.name)


# --- Doctor balance ---
