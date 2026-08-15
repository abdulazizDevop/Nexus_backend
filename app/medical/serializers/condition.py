from .common import *  # noqa: F401,F403 - header importlar + ui_status_q (public helper)

class MedicalConditionSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    severity_display = serializers.CharField(
        source="get_severity_display", read_only=True
    )
    added_by_name = serializers.CharField(
        source="added_by.full_name", read_only=True, default=None
    )
    added_by_role = serializers.CharField(
        source="added_by.role", read_only=True, default=None
    )

    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MedicalCondition
        fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "type",
            "type_display",
            "name",
            "severity",
            "severity_display",
            "discovered_at",
            "note",
            "added_by",
            "added_by_name",
            "added_by_role",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "added_by",
            "created_at",
        ]
