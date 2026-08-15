from .common import *  # noqa: F401,F403
from .common import _latest_message  # underscore (star bermaydi)


class ChatRoomListSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = ChatRoom
        fields = [
            "id",
            "room_type",
            "other_user",
            "last_message",
            "unread_count",
            "is_active",
            "updated_at",
        ]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_other_user(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        # prefetch_related("participants") keshidan foydalanamiz — .exclude().first()
        # har room uchun yangi query qilardi (N+1), .all() esa prefetch'dan keladi.
        other = next(
            (u for u in obj.participants.all() if u.id != request.user.id), None
        )
        if not other:
            return None
        return {
            "id": other.id,
            "full_name": other.full_name,
            "avatar": generate_download_url(other.avatar) if other.avatar else None,
        }

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_last_message(self, obj):
        msg = _latest_message(obj)
        if not msg:
            return None
        return {
            "id": msg.id,
            "content": msg.content[:100] if msg.content else msg.file_name,
            "message_type": msg.message_type,
            "sender": msg.sender_id,
            "created_at": msg.created_at.isoformat(),
        }


class ChatRoomDetailSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = [
            "id",
            "room_type",
            "participants",
            "is_active",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_participants(self, obj):
        return [
            {
                "id": u.id,
                "full_name": u.full_name,
                "avatar": generate_download_url(u.avatar) if u.avatar else None,
                "role": u.role,
            }
            for u in obj.participants.all()
        ]


class ChatRoomCreateSerializer(serializers.Serializer):
    """Consultation room yaratish.

    Patient: doctor_id yuboradi.
    Doctor: patient_id yuboradi.
    Ikkalasidan biri majburiy.
    """

    doctor_id = serializers.IntegerField(required=False)
    patient_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if not attrs.get("doctor_id") and not attrs.get("patient_id"):
            raise serializers.ValidationError(
                "doctor_id yoki patient_id dan biri majburiy."
            )
        return attrs
