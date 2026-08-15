from .common import *  # noqa: F401,F403

from ..models import MedicalCondition, RoadmapStep


class RoadmapStepSerializer(serializers.ModelSerializer):
    period_display = serializers.CharField(source="get_period_display", read_only=True)
    is_habit = serializers.BooleanField(read_only=True)

    class Meta:
        model = RoadmapStep
        fields = [
            "id", "period", "period_display", "order",
            "title", "description", "specialist",
            "treatment", "status", "is_habit",
            "completed_at", "created_at",
        ]
        read_only_fields = ["id", "status", "completed_at", "created_at"]


class RoadmapConditionSerializer(serializers.ModelSerializer):
    """Navigator aktiv tashxisi (kasallik pasporti ma'lumotlari)."""

    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = MedicalCondition
        fields = [
            "id", "type", "type_display", "name",
            "icd10", "plain_explanation", "is_active",
            "discovered_at", "created_at",
        ]
        read_only_fields = fields


class RoadmapSetupStepSerializer(serializers.Serializer):
    """Setup'da keladigan bitta qadam."""

    period = serializers.ChoiceField(choices=RoadmapStep.Period.choices)
    order = serializers.IntegerField(required=False, default=0, min_value=0)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    specialist = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )


class RoadmapSetupSerializer(serializers.Serializer):
    """POST /medical/roadmap/setup/ body — tashxis + qadamlar bitta so'rovda."""

    condition = serializers.DictField()
    steps = RoadmapSetupStepSerializer(many=True, allow_empty=False)

    def validate_condition(self, value):
        name = (value.get("name") or "").strip()
        if not name:
            raise serializers.ValidationError("condition.name majburiy.")
        return {
            "name": name,
            "icd10": (value.get("icd10") or "").strip()[:10],
            "plain_explanation": value.get("plain_explanation") or "",
            "type": value.get("type") or MedicalCondition.Type.CHRONIC,
        }
