from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _has_image, _image_url  # underscore helper (star bermaydi)

class DietMessageSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = DietMessage
        fields = [
            "id",
            "role",
            "content",
            "image_key",
            "image_url",
            "metadata",
            "tokens_input",
            "tokens_output",
            "is_blocked",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return _image_url(obj.image_key)

class DietConversationListSerializer(serializers.ModelSerializer):
    """Suhbatlar ro'yxati uchun (qisqa)."""

    last_message = serializers.SerializerMethodField()
    last_image_url = serializers.SerializerMethodField()
    images_count = serializers.SerializerMethodField()
    messages_count = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_phone = serializers.CharField(source="user.phone", read_only=True)

    class Meta:
        model = DietConversation
        fields = [
            "id",
            "user_id",
            "user_name",
            "user_phone",
            "title",
            "language",
            "is_archived",
            "messages_count",
            "images_count",
            "last_image_url",
            "last_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "role": {"type": "string"},
                "content": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
                "has_image": {"type": "boolean"},
            },
        }
    )
    def get_last_message(self, obj):
        # prefetch'langan messages'ni Python'da ishlash (qo'shimcha so'rovsiz).
        msgs = obj.messages.all()
        if not msgs:
            return None
        msg = max(msgs, key=lambda m: m.created_at)
        return {
            "role": msg.role,
            "content": msg.content[:120],
            "has_image": bool(msg.image_key),
            "created_at": msg.created_at.isoformat(),
        }

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_last_image_url(self, obj):
        """Oxirgi rasm yuborilgan xabarning URL'ini qaytaradi (thumbnail uchun)."""
        image_msgs = [m for m in obj.messages.all() if _has_image(m)]
        if not image_msgs:
            return None
        msg = max(image_msgs, key=lambda m: m.created_at)
        return _image_url(msg.image_key)

    @extend_schema_field(serializers.IntegerField())
    def get_images_count(self, obj):
        return sum(1 for m in obj.messages.all() if _has_image(m))

    @extend_schema_field(serializers.IntegerField())
    def get_messages_count(self, obj):
        return len(obj.messages.all())

class DietConversationDetailSerializer(serializers.ModelSerializer):
    """Bitta suhbat + barcha xabarlar + stats."""

    messages = DietMessageSerializer(many=True, read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_phone = serializers.CharField(source="user.phone", read_only=True)
    messages_count = serializers.SerializerMethodField()
    images_count = serializers.SerializerMethodField()
    confirmed_entries_count = serializers.SerializerMethodField()
    total_tokens = serializers.SerializerMethodField()

    class Meta:
        model = DietConversation
        fields = [
            "id",
            "user_id",
            "user_name",
            "user_phone",
            "title",
            "language",
            "is_archived",
            "messages_count",
            "images_count",
            "confirmed_entries_count",
            "total_tokens",
            "messages",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField())
    def get_messages_count(self, obj):
        return len(obj.messages.all())

    @extend_schema_field(serializers.IntegerField())
    def get_images_count(self, obj):
        return sum(1 for m in obj.messages.all() if _has_image(m))

    @extend_schema_field(serializers.IntegerField())
    def get_confirmed_entries_count(self, obj):
        """Ushbu suhbat orqali confirmed qilingan DietEntry soni."""
        return DietEntry.objects.filter(ai_message__conversation=obj).count()

    @extend_schema_field(serializers.IntegerField())
    def get_total_tokens(self, obj):
        # prefetch'langan messages'dan Python'da yig'amiz (qo'shimcha so'rovsiz).
        return sum(
            (m.tokens_input or 0) + (m.tokens_output or 0) for m in obj.messages.all()
        )

class DietConversationCreateSerializer(serializers.ModelSerializer):
    """Yangi suhbat yaratish."""

    class Meta:
        model = DietConversation
        fields = ["id", "title", "language"]
        read_only_fields = ["id"]

    def validate_language(self, value):
        if value not in ("uz", "uz-cyrl", "ru"):
            raise serializers.ValidationError(
                "Til: uz, uz-cyrl yoki ru bo'lishi kerak."
            )
        return value

class SendMessageSerializer(serializers.Serializer):
    """Yangi xabar yuborish (text only)."""

    content = serializers.CharField(min_length=1, max_length=4000)

class MessageFeedbackSerializer(serializers.Serializer):
    """Assistant xabari uchun sifat feedbacki (AI tahlili to'g'ri/noto'g'ri)."""

    verdict = serializers.ChoiceField(choices=["correct", "incorrect"])
    comment = serializers.CharField(
        required=False, allow_blank=True, max_length=1000,
        help_text="Ixtiyoriy izoh (ayniqsa incorrect bo'lganda foydali).",
    )
