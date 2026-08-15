from django.core.validators import FileExtensionValidator
from rest_framework import serializers

from app.pharmacy.models import Drug, DrugImportLog

# Import .xls fayl uchun maksimal hajm — web worker xotira/CPU DoS'dan himoya.
MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10MB


class DrugSerializer(serializers.ModelSerializer):
    """Public + admin uchun yagona serializer (write hammaga ochiq emas — view'da boshqariladi)."""

    category_label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = Drug
        fields = [
            "id",
            "category",
            "category_label",
            "name",
            "is_active",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "category_label",
            "source",
            "created_at",
            "updated_at",
        ]


class DrugImportLogSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    uploaded_by_name = serializers.CharField(
        source="uploaded_by.full_name", read_only=True
    )

    class Meta:
        model = DrugImportLog
        fields = [
            "id",
            "filename",
            "category",
            "category_label",
            "uploaded_by_name",
            "total_rows",
            "created_count",
            "updated_count",
            "skipped_count",
            "error_count",
            "is_active_default",
            "created_at",
        ]
        read_only_fields = fields


class DrugImportUploadSerializer(serializers.Serializer):
    """Admin paneldan Excel upload qilish uchun."""

    file = serializers.FileField(
        validators=[FileExtensionValidator(allowed_extensions=["xls"])]
    )
    category = serializers.ChoiceField(choices=Drug.Category.choices)
    is_active = serializers.BooleanField(
        default=True,
        help_text="False — annulirovannye yozuvlar uchun",
    )

    def validate_file(self, value):
        if value.size > MAX_IMPORT_BYTES:
            raise serializers.ValidationError(
                f"Fayl hajmi {MAX_IMPORT_BYTES // (1024 * 1024)}MB dan oshmasligi kerak."
            )
        return value
