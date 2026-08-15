from rest_framework import serializers

from core.serializers import TranslatableFieldsMixin

from .models import GuideVideo


class GuideVideoSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Video qo'llanma serializer.

    O'qish:
      - `?lang=ru` → `title/description/video_url` ruschasi (string)
      - `?include_translations=1` (admin) → to'liq dict {uz,ru,cyr}

    Yozish (admin): har translatable maydon dict yuboradi.
    """

    translatable_fields = ["title", "description", "video_url"]

    class Meta:
        model = GuideVideo
        fields = [
            "id",
            "title",
            "description",
            "video_url",
            "thumbnail_url",
            "duration_seconds",
            "app_scope",
            "category",
            "order",
            "is_active",
            "is_featured",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        # Yaratishda title va video_url majburiy (kamida bitta til).
        is_create = self.instance is None

        def _has_content(value):
            return isinstance(value, dict) and any(
                str(v).strip() for v in value.values()
            )

        if is_create:
            if not _has_content(attrs.get("title")):
                raise serializers.ValidationError(
                    {"title": "Sarlavha majburiy (kamida bitta til)."}
                )
            if not _has_content(attrs.get("video_url")):
                raise serializers.ValidationError(
                    {"video_url": "Video havola majburiy (kamida bitta til)."}
                )
        return attrs
