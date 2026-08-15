from .common import *  # noqa: F401,F403


class DailySituationCheckupSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    patient_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DailySituationCheckup
        fields = [
            "id",
            "user",  # User.id (legacy)
            "patient_profile_id",  # Patient.id (yangi)
            "date",
            "status",
            "status_display",
            "note",
        ]
        read_only_fields = ["id", "user", "patient_profile_id", "date"]
