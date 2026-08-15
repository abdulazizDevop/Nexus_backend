from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class ProFeatureFlagSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Pro feature — `label` va `description` 3 tilli JSON."""

    translatable_fields = ["label", "description"]

    class Meta:
        model = ProFeatureFlag
        fields = ["id", "key", "label", "icon", "description", "is_active", "order"]
        read_only_fields = ["id"]
class ProPlanSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Pro plan — `name` 3 tilli JSON."""

    translatable_fields = ["name"]

    class Meta:
        model = ProPlan
        fields = [
            "id",
            "name",
            "duration_days",
            "price",
            "discount_percent",
            "is_popular",
            "is_active",
            "order",
        ]
        read_only_fields = ["id"]
class ProPlanPublicSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Patient uchun — faqat aktiv planlar + features. `name` til'ga moslashtirilgan."""

    translatable_fields = ["name"]
    features = serializers.SerializerMethodField()

    class Meta:
        model = ProPlan
        fields = [
            "id",
            "name",
            "duration_days",
            "price",
            "discount_percent",
            "is_popular",
            "features",
        ]

    @extend_schema_field(ProFeatureFlagSerializer(many=True))
    def get_features(self, obj):
        features = ProFeatureFlag.objects.filter(is_active=True).order_by("order")
        return ProFeatureFlagSerializer(features, many=True).data
class GrantProSerializer(serializers.Serializer):
    """Admin user'ga manual Pro obuna beradi (to'lovsiz)."""

    duration_days = serializers.IntegerField(min_value=1, max_value=3650)
    reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500
    )
class ProSubscriptionSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(read_only=True) # plan.name JSONField, oldin CharField raw dict qaytarardi.
    plan_name = serializers.SerializerMethodField() # Patient profile ID
    patient_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProSubscription
        fields = [
            "id",
            "user",
            "patient_profile_id",
            "plan",
            "plan_name",
            "plan_snapshot",
            "starts_at",
            "expires_at",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields

    def get_plan_name(self, obj):
        if not obj.plan:
            # Plan o'chirilgan bo'lsa snapshot'dan olamiz
            snapshot_name = (obj.plan_snapshot or {}).get("name")
            return pick_for(self.context, snapshot_name) if snapshot_name else ""
        return pick_for(self.context, obj.plan.name)
class SubscribeRequestSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()
    provider = serializers.ChoiceField(choices=Payment.Provider.choices)


# --- Doctor tariflari ---
class MyProStatusSerializer(serializers.Serializer):
    """`/pro/me/` ning javobi — aktiv obuna bo'lsa subscription qaytariladi."""

    is_active = serializers.BooleanField()
    subscription = ProSubscriptionSerializer(allow_null=True)
class RevokeProResponseSerializer(serializers.Serializer):
    """`/admin/users/{id}/revoke-pro/` ning javobi."""

    revoked_count = serializers.IntegerField(
        help_text="Bekor qilingan aktiv obunalar soni"
    )


# --- Doctor sales stats (dashboard) ---
