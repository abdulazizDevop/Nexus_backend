from rest_framework import serializers

from .models import DeviceToken, Notification


class DeviceTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceToken
        fields = [
            "id",
            "token",
            "device_id",
            "platform",
            "app_scope",
            "token_type",
            "environment",
            "device_name",
            "app_version",
            "is_active",
            "created_at",
            "last_used_at",
        ]
        read_only_fields = ["id", "is_active", "created_at", "last_used_at"]


class NotificationSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "type_label",
            "title",
            "body",
            "data",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields


class MarkReadSerializer(serializers.Serializer):
    """Bir nechta notificationlarni o'qildi qilish uchun."""

    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="O'qildi qilinadigan notification id lar ro'yxati",
    )
