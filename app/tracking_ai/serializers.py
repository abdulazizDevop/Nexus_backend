from rest_framework import serializers

from .models import AITrackingReport


class AITrackingReportSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)

    class Meta:
        model = AITrackingReport
        fields = [
            "id", "patient", "patient_profile", "patient_name",
            "period_start", "period_end",
            "summary", "detected_changes", "recommendations",
            "adherence_percent", "severity", "severity_display",
            "seen_at", "created_at",
        ]
        read_only_fields = fields
