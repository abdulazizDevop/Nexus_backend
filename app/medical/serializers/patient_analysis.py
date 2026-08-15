from .common import *  # noqa: F401,F403 - header importlar + ui_status_q (public helper)

class PatientAnalysisUploadUrlRequestSerializer(serializers.Serializer):
    """Patient analizini yuklash uchun S3 presigned URL — analysis hali yo'q.

    `count` orqali ko'p faylga bir vaqtda URL olish ham mumkin (response array).
    """

    file_type = serializers.ChoiceField(
        choices=[
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/heic",
            "image/webp",
        ],
        default="image/jpeg",
    )
    # max=5 - audit H8 (DO Spaces bill DoS himoyasi).
    count = serializers.IntegerField(min_value=1, max_value=5, default=1)

class _PatientUploadUrlItemSerializer(serializers.Serializer):
    upload_url = serializers.URLField()
    file_key = serializers.CharField()
    expires_in = serializers.IntegerField()

class PatientAnalysisUploadUrlResponseSerializer(serializers.Serializer):
    items = _PatientUploadUrlItemSerializer(many=True)

class _PatientUploadFileSerializer(serializers.Serializer):
    file_key = serializers.CharField(max_length=500)
    file_mime = serializers.CharField(max_length=80, required=False, allow_blank=True)
    file_size_bytes = serializers.IntegerField(required=False, allow_null=True)
    original_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )

class PatientAnalysisCreateSerializer(serializers.Serializer):
    """Patient o'zi tashabbus bilan analiz yaratadi.

    - `type_id` — AnalysisType ID (Qon/Siydik/UZI/ECG/Rentgen/Boshqa)
    - `title` — bemor qo'ygan ixtiyoriy nom
    - `recorded_at` — analiz topshirilgan sana
    - `files[]` — yuklangan fayllarning S3 key'lari (oldindan presigned URL orqali)
    - `patient_note` — bemor izohi (ixtiyoriy)

    Analiz bemorning barcha bog'langan doctorlariga avtomatik ko'rinadi —
    qabul qiluvchi tanlash kerak emas.
    """

    type_id = serializers.IntegerField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    recorded_at = serializers.DateField(required=False, allow_null=True)
    files = _PatientUploadFileSerializer(many=True, min_length=0, required=False)
    patient_note = serializers.CharField(required=False, allow_blank=True)
