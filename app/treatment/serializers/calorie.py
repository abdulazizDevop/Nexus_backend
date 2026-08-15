from .common import *  # noqa: F401,F403
from .common import _validate_doctor_patient_link  # underscore (star bermaydi)


class DailyCalorieLimitSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    set_by_name = serializers.CharField(
        source="set_by.full_name", read_only=True, default=None
    )
    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DailyCalorieLimit
        fields = [
            "id",
            "patient",
            "patient_profile_id",
            "doctor_profile_id",
            "patient_name",
            "calories",
            "carbs_limit",
            "protein_limit",
            "fat_limit",
            "set_by_name",
            "notes",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "patient",
            "patient_profile_id",
            "doctor_profile_id",
            "patient_name",
            "set_by_name",
            "updated_at",
        ]


class DailyCalorieLimitSetSerializer(serializers.Serializer):
    """Doctor bemorga kaloriya + macros chegarasi belgilash"""

    patient_id = serializers.IntegerField()
    calories = serializers.IntegerField(min_value=500, max_value=10000)
    carbs_limit = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=1000
    )
    protein_limit = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=500
    )
    fat_limit = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=500
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_patient_id(self, value):
        return _validate_doctor_patient_link(value, self.context)
