from .common import *  # noqa: F401,F403

from ..models import PrescriptionScan, Treatment

_IMAGE_MIMES = ["image/jpeg", "image/jpg", "image/png", "image/webp"]


class PrescriptionUploadUrlSerializer(serializers.Serializer):
    """POST /treatments/prescription/upload-url/ body."""

    file_type = serializers.ChoiceField(choices=_IMAGE_MIMES)


class PrescriptionAnalyzeSerializer(serializers.Serializer):
    """POST /treatments/prescription/analyze/ body."""

    image_key = serializers.CharField(max_length=500)


class PrescriptionItemSerializer(serializers.Serializer):
    """Tasdiqlashda keladigan bitta muolaja (bemor tahrir qilgan bo'lishi mumkin)."""

    title = serializers.CharField(max_length=255)
    type = serializers.ChoiceField(
        choices=Treatment.Type.choices, default=Treatment.Type.MEDICATION
    )
    dosage = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    times = serializers.ListField(
        child=serializers.RegexField(r"^\d{2}:\d{2}(:\d{2})?$"),
        required=False,
        default=list,
        max_length=12,
    )
    repeat = serializers.ChoiceField(
        choices=Treatment.Repeat.choices, default=Treatment.Repeat.DAILY
    )
    duration_days = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=730
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class PrescriptionConfirmSerializer(serializers.Serializer):
    """POST /treatments/prescription/{id}/confirm/ body."""

    items = PrescriptionItemSerializer(many=True, allow_empty=False)


class PrescriptionScanSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PrescriptionScan
        fields = [
            "id", "image_key", "status", "status_display",
            "summary", "ai_items", "ai_warnings",
            "created_treatment_ids", "created_at", "reviewed_at",
        ]
        read_only_fields = fields
