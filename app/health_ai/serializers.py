from rest_framework import serializers

from .models import AIHealthReport, AiConversation, AiMessage


class AIHealthReportSerializer(serializers.ModelSerializer):
    """Kunlik AI insight hisoboti (doctor uchun read-only)."""

    patient_name = serializers.CharField(source="patient.full_name", read_only=True)

    class Meta:
        model = AIHealthReport
        fields = [
            "id", "patient_id", "patient_name", "period_start", "period_end",
            "summary", "detected_changes", "severity", "seen_at", "created_at",
        ]
        read_only_fields = fields


class AiMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiMessage
        fields = ["id", "role", "content", "metadata", "created_at"]
        read_only_fields = fields


class AiConversationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    message_count = serializers.IntegerField(source="messages.count", read_only=True)

    class Meta:
        model = AiConversation
        fields = [
            "id", "patient_id", "patient_name", "title", "language",
            "is_archived", "message_count", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "patient_name", "title", "message_count", "created_at", "updated_at",
        ]
