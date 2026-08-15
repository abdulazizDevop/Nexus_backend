from .common import *  # noqa: F401,F403


class AccountDeletionRequestSerializer(serializers.Serializer):
    """Autentifikatsiyasiz akkaunt o'chirish so'rovi (mediik.uz/delete form)."""

    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )
    confirm = serializers.BooleanField(required=True)

    def validate_phone(self, value):
        return validate_uz_phone(value)

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                "O'chirishga rozi ekanligingizni tasdiqlashingiz kerak."
            )
        return value
