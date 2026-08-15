from .common import *  # noqa: F401,F403 - header importlar + ui_status_q (public helper)
from .common import _signed_download  # underscore helper (star bermaydi)

class AudioUploadUrlRequestSerializer(serializers.Serializer):
    """Medical audio yuklash uchun presigned URL so'rovi."""

    file_type = serializers.ChoiceField(
        choices=[
            "audio/webm",
            "audio/mp3",
            "audio/mpeg",
            "audio/mp4",
            "audio/wav",
            "audio/ogg",
            "audio/x-m4a",
            "audio/aac",
        ],
        default="audio/webm",
    )

class AudioUploadUrlResponseSerializer(serializers.Serializer):
    upload_url = serializers.URLField()
    audio_key = serializers.CharField()
    expires_in = serializers.IntegerField()

class MedicalNoteAIDraftRequestSerializer(serializers.Serializer):
    """Doctor ovoz orqali yozuv diktovka qiladi, AI draft tayyorlaydi."""

    patient_id = serializers.IntegerField()
    audio_key = serializers.CharField(max_length=500)
    language = serializers.ChoiceField(
        choices=["uz", "uz-cyrl", "ru"],
        required=False,
        default="uz",
    )

class MedicalNoteAIDraftResponseSerializer(serializers.Serializer):
    transcription = serializers.CharField()
    draft_text = serializers.CharField()
    tokens_used = serializers.IntegerField()

class MedicalNoteImageSerializer(serializers.ModelSerializer):
    """MedicalNote'ga ilova qilingan rasm."""

    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MedicalNoteImage
        fields = [
            "id",
            "file_key",
            "file_mime",
            "file_size_bytes",
            "original_name",
            "order",
            "uploaded_at",
            "file_url",
        ]
        read_only_fields = ["id", "uploaded_at", "file_url"]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_file_url(self, obj):
        return _signed_download(obj.file_key)

class _MedicalNoteImageInputSerializer(serializers.Serializer):
    """MedicalNote create payload'ida bitta rasm uchun input."""

    file_key = serializers.CharField(max_length=500)
    file_mime = serializers.CharField(max_length=80, required=False, allow_blank=True)
    file_size_bytes = serializers.IntegerField(required=False, allow_null=True)
    original_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )

class MedicalNoteImageUploadUrlRequestSerializer(serializers.Serializer):
    """MedicalNote rasm yuklash uchun presigned URL so'rovi."""

    file_type = serializers.ChoiceField(
        choices=[
            "image/jpeg",
            "image/png",
            "image/heic",
            "image/webp",
        ],
        default="image/jpeg",
    )
    count = serializers.IntegerField(min_value=1, max_value=5, default=1)

class _MedicalNoteImageUploadUrlItemSerializer(serializers.Serializer):
    upload_url = serializers.URLField()
    file_key = serializers.CharField()
    expires_in = serializers.IntegerField()

class MedicalNoteImageUploadUrlResponseSerializer(serializers.Serializer):
    items = _MedicalNoteImageUploadUrlItemSerializer(many=True)

class MedicalNoteSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )
    created_by_role = serializers.CharField(
        source="created_by.role", read_only=True, default=None
    )

    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_profile_id = serializers.IntegerField(read_only=True)

    text = serializers.CharField(required=False, allow_blank=True)
    images = MedicalNoteImageSerializer(many=True, read_only=True)
    images_input = _MedicalNoteImageInputSerializer(
        many=True,
        write_only=True,
        required=False,
        help_text=(
            "Yangi rasm ilovasi. Avval /medical/notes/image-upload-url/ "
            "orqali file_key olinadi, keyin shu yerda ro'yxat sifatida yuboriladi."
        ),
    )

    class Meta:
        model = MedicalNote
        fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "text",
            "created_by",
            "created_by_name",
            "created_by_role",
            "created_at",
            "updated_at",
            "images",
            "images_input",
        ]
        read_only_fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        text = (attrs.get("text") or "").strip()
        images_input = attrs.get("images_input") or []
        if not text and not images_input:
            raise serializers.ValidationError(
                "Matn yoki kamida bitta rasm bo'lishi kerak."
            )
        return attrs

    def create(self, validated_data):
        images_input = validated_data.pop("images_input", [])
        note = super().create(validated_data)
        if images_input:
            uploaded_by = note.created_by
            MedicalNoteImage.objects.bulk_create(
                [
                    MedicalNoteImage(
                        note=note,
                        file_key=item["file_key"],
                        file_mime=item.get("file_mime", ""),
                        file_size_bytes=item.get("file_size_bytes"),
                        original_name=item.get("original_name", ""),
                        order=idx,
                        uploaded_by=uploaded_by,
                    )
                    for idx, item in enumerate(images_input)
                ]
            )
        return note

    def update(self, instance, validated_data):
        images_input = validated_data.pop("images_input", None)
        instance = super().update(instance, validated_data)
        if images_input is not None:
            existing_count = instance.images.count()
            MedicalNoteImage.objects.bulk_create(
                [
                    MedicalNoteImage(
                        note=instance,
                        file_key=item["file_key"],
                        file_mime=item.get("file_mime", ""),
                        file_size_bytes=item.get("file_size_bytes"),
                        original_name=item.get("original_name", ""),
                        order=existing_count + idx,
                        uploaded_by=instance.created_by,
                    )
                    for idx, item in enumerate(images_input)
                ]
            )
        return instance


# --- Analiz katalogi ---
