from .common import *  # noqa: F401,F403


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.full_name", read_only=True)
    sender_role = serializers.CharField(source="sender.role", read_only=True)
    sender_admin_type = serializers.CharField(
        source="sender.admin_type", read_only=True, default=None
    )
    sender_avatar = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "sender",
            "sender_name",
            "sender_role",
            "sender_admin_type",
            "sender_scope",
            "sender_avatar",
            "message_type",
            "content",
            "file_key",
            "file_url",
            "file_name",
            "file_size",
            "file_type",
            "audio_status",
            "transcript",
            "transcript_status",
            "reply_to",
            "is_read",
            "read_at",
            "is_ai",
            "created_at",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_sender_avatar(self, obj):
        if obj.sender.avatar:
            return generate_download_url(obj.sender.avatar)
        return None

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_file_url(self, obj):
        if obj.file_key:
            return generate_download_url(obj.file_key)
        return None


class UploadURLSerializer(serializers.Serializer):
    """Presigned upload URL so'rash"""

    file_name = serializers.CharField(max_length=255)
    file_type = serializers.CharField(max_length=100)
    file_size = serializers.IntegerField()


# --- Admin serializers ---
