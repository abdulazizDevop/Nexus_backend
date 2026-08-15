from .common import *  # noqa: F401,F403


class CallInitSerializer(serializers.Serializer):
    """Call boshlash uchun"""

    call_type = serializers.ChoiceField(
        choices=[("video", "Video"), ("audio", "Audio")]
    )


class CallSessionSerializer(serializers.ModelSerializer):
    caller_name = serializers.CharField(source="caller.full_name", read_only=True)
    callee_name = serializers.CharField(source="callee.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    duration_display = serializers.CharField(read_only=True)

    class Meta:
        from ..models import CallSession

        model = CallSession
        fields = [
            "id",
            "room",
            "caller",
            "caller_name",
            "callee",
            "callee_name",
            "call_type",
            "status",
            "status_display",
            "room_name",
            "started_at",
            "ended_at",
            "duration",
            "duration_display",
            "created_at",
        ]
        read_only_fields = fields
