from .common import *  # noqa: F401,F403 - header importlar + ui_status_q (public helper)
from .analysis import AnalysisListSerializer
from .condition import MedicalConditionSerializer

class MedicalCardSerializer(serializers.ModelSerializer):
    blood_type_display = serializers.CharField(
        source="get_blood_type_display", read_only=True
    )
    current_status_display = serializers.CharField(
        source="get_current_status_display", read_only=True
    )
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_phone = serializers.CharField(source="user.phone", read_only=True)
    updated_by_name = serializers.CharField(
        source="updated_by.full_name", read_only=True, default=None
    )

    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MedicalCard
        fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "user_name",
            "user_phone",
            "blood_type",
            "blood_type_display",
            "height_cm",
            "weight_kg",
            "primary_disease",
            "current_status",
            "current_status_display",
            "notes",
            "updated_at",
            "updated_by",
            "updated_by_name",
        ]
        read_only_fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "updated_at",
            "updated_by",
        ]

class _CardSummaryUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    phone = serializers.CharField()
    age = serializers.IntegerField(allow_null=True)
    gender = serializers.CharField(allow_null=True)
    avatar_url = serializers.URLField(allow_null=True)

class MedicalCardSummarySerializer(serializers.Serializer):
    patient = _CardSummaryUserSerializer()
    card = MedicalCardSerializer()
    analyses_recent = AnalysisListSerializer(many=True)
    analyses_pending = AnalysisListSerializer(many=True)
    analyses_total = serializers.IntegerField()
    analyses_pending_count = serializers.IntegerField()
    allergies = MedicalConditionSerializer(many=True)
    allergies_count = serializers.IntegerField()
