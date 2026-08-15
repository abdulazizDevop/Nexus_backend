from .common import *  # noqa: F401,F403
from .common import _latest_message  # underscore (star bermaydi)


class AdminChatRoomListSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    message_count = serializers.IntegerField(read_only=True, default=0)
    unread_count = serializers.IntegerField(read_only=True, default=0)
    last_message_at = serializers.DateTimeField(read_only=True, default=None)
    # Support: bemor oxirgi yozgan, admin javob bermagan (is_read'ga bog'liq emas).
    awaiting_reply = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = ChatRoom
        fields = [
            "id",
            "room_type",
            "participants",
            "message_count",
            "unread_count",
            "last_message_at",
            "awaiting_reply",
            "is_active",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_participants(self, obj):
        return [
            {"id": u.id, "full_name": u.full_name, "role": u.role}
            for u in obj.participants.all()
        ]


class AdminChatRoomDetailSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    message_count = serializers.IntegerField(read_only=True, default=0)
    unread_count = serializers.IntegerField(read_only=True, default=0)
    last_message_at = serializers.DateTimeField(read_only=True, default=None)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = [
            "id",
            "room_type",
            "participants",
            "message_count",
            "unread_count",
            "last_message_at",
            "last_message",
            "is_active",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_participants(self, obj):
        from ..utils import is_online

        return [
            {
                "id": u.id,
                "full_name": u.full_name,
                "phone": u.phone,
                "role": u.role,
                "is_online": is_online(u.id),
            }
            for u in obj.participants.all()
        ]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_last_message(self, obj):
        msg = _latest_message(obj)
        if not msg:
            return None
        return {
            "id": msg.id,
            "sender": msg.sender_id,
            "sender_name": msg.sender.full_name,
            "content": msg.content[:100] if msg.content else msg.file_name,
            "message_type": msg.message_type,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat(),
        }
