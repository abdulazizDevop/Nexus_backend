from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + konstantalar
from .common import _avatar_url


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        exclude = ["id", "user"]


class UserSerializer(serializers.ModelSerializer):
    settings = UserSettingsSerializer(read_only=True)
    referral_link = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    is_root = serializers.BooleanField(source="is_root_admin", read_only=True)

    allowed_roles = serializers.ListField(read_only=True)
    has_doctor_profile = serializers.BooleanField(read_only=True)
    is_verified_doctor = serializers.BooleanField(read_only=True)

    # Role-context ID'lar — Patient va DoctorProfile alohida row'lar.
    # Mobile/admin frontend chat/call/appointment'larda bu ID'lardan foydalanadi.
    patient_id = serializers.SerializerMethodField()
    doctor_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "full_name",
            "role",
            "active_role",
            "allowed_roles",
            "patient_id",
            "doctor_id",
            "has_doctor_profile",
            "is_verified_doctor",
            "sex",
            "birth_date",
            "avatar",
            "admin_type",
            "is_root",
            "referral_code",
            "referral_link",
            "telegram_chat_id",
            "is_active",
            "date_joined",
            "settings",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_patient_id(self, obj):
        profile = getattr(obj, "patient_profile", None)
        return profile.id if profile else None

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_doctor_id(self, obj):
        profile = getattr(obj, "doctor_profile", None)
        return profile.id if profile else None

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return _avatar_url(obj.avatar)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_referral_link(self, obj):
        if not obj.referral_code:
            return None
        return f"https://{settings.APP_DOMAIN}/ref/{obj.referral_code}"


class UserUpdateSerializer(serializers.ModelSerializer):
    settings = UserSettingsSerializer(required=False)
    avatar = serializers.CharField(
        max_length=500,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="DO Spaces key (avatar-upload-url dan olingan file_key)",
    )

    class Meta:
        model = User
        fields = ["full_name", "sex", "birth_date", "avatar", "settings"]

    def validate_avatar(self, value):
        # XAVFSIZLIK: avatar key FAQAT o'z prefiksida bo'lsin — aks holda client
        # ixtiyoriy S3 key berib (boshqa user avatari, sertifikat...) imzolangan
        # URL oldirishi mumkin (IDOR). Upload-url har doim avatars/{uid}/ beradi.
        if not value:
            return value
        request = self.context.get("request")
        uid = getattr(getattr(request, "user", None), "id", None)
        if uid is None or not str(value).startswith(f"avatars/{uid}/"):
            raise serializers.ValidationError("Noto'g'ri avatar key.")
        return value

    def update(self, instance, validated_data):
        settings_data = validated_data.pop("settings", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if settings_data:
            user_settings, _ = UserSettings.objects.get_or_create(user=instance)
            for attr, value in settings_data.items():
                setattr(user_settings, attr, value)
            user_settings.save()

        return instance


