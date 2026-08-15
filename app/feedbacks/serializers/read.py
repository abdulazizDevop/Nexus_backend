from .common import *  # noqa: F401,F403


DEFAULT_DISPLAY_NAME = "Foydalanuvchi"


def _mask_full_name(full_name):
    """To'liq ismni anonimlashtirilgan formatga aylantiradi ('Ali Karimov' → 'Ali K.')."""
    full_name = (full_name or "").strip()
    if not full_name:
        return DEFAULT_DISPLAY_NAME
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[1][0].upper()}."


class ReviewTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewTag
        fields = ["slug", "label_uz", "label_ru", "sentiment", "icon"]


class ReviewSerializer(serializers.ModelSerializer):
    """Public read — doctor sahifasida ko'rsatish uchun."""

    patient_name = serializers.SerializerMethodField()
    patient_avatar = serializers.SerializerMethodField()
    doctor_id = serializers.IntegerField(read_only=True)
    appointment_id = serializers.IntegerField(read_only=True)
    patient_profile_id = serializers.IntegerField(read_only=True)
    tags = ReviewTagSerializer(many=True, read_only=True)

    class Meta:
        model = Review
        # Diqqat: `patient` (User PK) public javobda OSHKOR QILINMAYDI —
        # anonimlik niyatiga (patient_name qisqartirilgan) mos bo'lishi uchun.
        fields = [
            "id",
            "patient_profile_id",
            "doctor_id",
            "appointment_id",
            "rating",
            "comment",
            "tags",
            "patient_name",
            "patient_avatar",
            "is_edited",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_patient_avatar(self, obj):
        return generate_download_url(obj.patient.avatar) if obj.patient.avatar else None

    @extend_schema_field(serializers.CharField())
    def get_patient_name(self, obj):
        return _mask_full_name(obj.patient.full_name)
