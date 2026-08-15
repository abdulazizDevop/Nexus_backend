from .common import *  # noqa: F401,F403 - header importlar + ui_status_q (public helper)

class AnalysisCreateSerializer(serializers.ModelSerializer):
    """Doctor analiz tayinlaganda — kirish payloadi."""

    patient_id = serializers.IntegerField(write_only=True)
    deadline_days = serializers.IntegerField(
        write_only=True,
        required=False,
        min_value=1,
        max_value=365,
        help_text="Bugundan boshlab necha kun ichida topshirish kerakligi.",
    )
    custom_indicators = serializers.ListField(
        child=serializers.CharField(max_length=100, trim_whitespace=True),
        required=False,
        max_length=20,
        allow_empty=True,
        help_text="Doctor 'Boshqa' tugmasi orqali qo'shgan qo'shimcha ko'rsatkichlar (erkin matn ro'yxati).",
    )
    custom_preparations = serializers.ListField(
        child=serializers.CharField(max_length=200, trim_whitespace=True),
        required=False,
        max_length=20,
        allow_empty=True,
        help_text="Doctor 'Boshqa' tugmasi orqali qo'shgan qo'shimcha tayyorgarliklar (erkin matn ro'yxati).",
    )

    class Meta:
        model = Analysis
        fields = [
            "id",
            "patient_id",
            "type",
            "indicators",
            "custom_indicators",
            "preparations",
            "custom_preparations",
            "deadline_at",
            "deadline_days",
            "note",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "deadline_at": {"required": False},
        }

    def validate(self, data):
        if "deadline_at" not in data and "deadline_days" not in data:
            raise serializers.ValidationError(
                "deadline_at yoki deadline_days ko'rsatilishi shart."
            )
        if "deadline_at" not in data:
            data["deadline_at"] = timezone.now() + timedelta(
                days=data.pop("deadline_days")
            )
        else:
            data.pop("deadline_days", None)

        # Indicator type'lari analiz turiga mos kelishi kerak
        analysis_type = data.get("type")
        indicators = data.get("indicators") or []
        if analysis_type and indicators:
            wrong = [i for i in indicators if i.type_id != analysis_type.id]
            if wrong:
                raise serializers.ValidationError(
                    "Tanlangan ko'rsatkichlar analiz turiga mos emas."
                )
        return data

class AnalysisUpdateSerializer(serializers.ModelSerializer):
    """Doctor analizni tahrirlaganda — faqat prescribed bo'lsa."""

    custom_indicators = serializers.ListField(
        child=serializers.CharField(max_length=100, trim_whitespace=True),
        required=False,
        max_length=20,
        allow_empty=True,
    )
    custom_preparations = serializers.ListField(
        child=serializers.CharField(max_length=200, trim_whitespace=True),
        required=False,
        max_length=20,
        allow_empty=True,
    )

    class Meta:
        model = Analysis
        fields = [
            "type",
            "indicators",
            "custom_indicators",
            "preparations",
            "custom_preparations",
            "deadline_at",
            "note",
        ]

    def validate(self, data):
        instance = self.instance
        if instance and instance.status != Analysis.Status.PRESCRIBED:
            raise serializers.ValidationError(
                "Faqat 'prescribed' statusdagi analizni tahrirlash mumkin."
            )

        analysis_type = data.get("type", getattr(instance, "type", None))
        indicators = data.get("indicators")
        if indicators is None and instance is not None:
            indicators = list(instance.indicators.all())
        if analysis_type and indicators:
            wrong = [i for i in indicators if i.type_id != analysis_type.id]
            if wrong:
                wrong_ids = sorted({i.id for i in wrong})
                wrong_types = sorted({i.type_id for i in wrong})
                raise serializers.ValidationError(
                    {
                        "indicators": (
                            f"Quyidagi ko'rsatkichlar analiz turiga ({analysis_type.id}) "
                            f"mos emas: id={wrong_ids} (ular type_id={wrong_types} ga tegishli). "
                            f"`type` ni ham yangilang yoki to'g'ri ko'rsatkichlarni tanlang."
                        )
                    }
                )
        return data

class AnalysisCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)

class AnalysisReviewSerializer(serializers.Serializer):
    verdict = serializers.CharField()

class AnalysisResultUploadUrlRequestSerializer(serializers.Serializer):
    file_type = serializers.ChoiceField(
        choices=[
            "application/pdf",
            "image/jpeg",
            "image/png",
            "image/heic",
            "image/webp",
        ],
        default="application/pdf",
    )

class AnalysisResultUploadUrlResponseSerializer(serializers.Serializer):
    upload_url = serializers.URLField()
    file_key = serializers.CharField()
    expires_in = serializers.IntegerField()

class _SubmitValueItemSerializer(serializers.Serializer):
    indicator_id = serializers.IntegerField()
    value = serializers.DecimalField(max_digits=12, decimal_places=3)

class AnalysisSubmitSerializer(serializers.Serializer):
    file_key = serializers.CharField(max_length=500, required=False, allow_blank=True)
    file_mime = serializers.CharField(max_length=80, required=False, allow_blank=True)
    files = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text=(
            "Bir nechta fayl uchun: [{file_key, file_mime?, file_size_bytes?, "
            "original_name?}]. Berilsa, mavjud fayllar bilan almashtiriladi."
        ),
    )
    patient_note = serializers.CharField(required=False, allow_blank=True)
    values = _SubmitValueItemSerializer(many=True, required=False)


# --- Patient-initiated upload flow ---

class AnalysisMarkSeenByDoctorResponseSerializer(serializers.Serializer):
    """Doctor analizni ko'rdim — KO'RILDI status response."""

    id = serializers.IntegerField()
    doctor_viewed_at = serializers.DateTimeField()
    ui_status = serializers.CharField()


# --- Tibbiy karta summary (doctor side) ---
