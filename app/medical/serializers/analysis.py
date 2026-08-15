from .common import *  # noqa: F401,F403 - header importlar + ui_status_q (public helper)
from .common import _compute_ui_status, _days_left, _doctor_brief, _signed_download  # underscore helper (star bermaydi)

class AnalysisIndicatorSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """`name` 3 tilli JSON. `?lang=` da string, `?include_translations=1` da dict."""

    translatable_fields = ["name"]

    class Meta:
        model = AnalysisIndicator
        fields = [
            "id",
            "type",
            "name",
            "code",
            "unit",
            "normal_min",
            "normal_max",
            "order",
        ]
        read_only_fields = ["id"]

class AnalysisPreparationSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """`title` va `description` 3 tilli JSON."""

    translatable_fields = ["title", "description"]

    class Meta:
        model = AnalysisPreparation
        fields = ["id", "type", "title", "description", "order"]
        read_only_fields = ["id"]

class AnalysisTypeSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """`name` va `description` 3 tilli JSON."""

    translatable_fields = ["name", "description"]
    indicators = AnalysisIndicatorSerializer(many=True, read_only=True)
    preparations = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisType
        fields = [
            "id",
            "name",
            "code",
            "category",
            "icon",
            "description",
            "is_active",
            "order",
            "indicators",
            "preparations",
        ]
        read_only_fields = ["id"]

    @extend_schema_field(AnalysisPreparationSerializer(many=True))
    def get_preparations(self, obj):
        qs = AnalysisPreparation.objects.filter(Q(type=obj) | Q(type__isnull=True))
        return AnalysisPreparationSerializer(qs, many=True).data


# --- Analiz natija qiymatlari ---

class AnalysisResultValueSerializer(serializers.ModelSerializer):
    indicator_name = serializers.CharField(source="indicator.name", read_only=True)
    indicator_unit = serializers.CharField(source="indicator.unit", read_only=True)
    indicator_code = serializers.CharField(source="indicator.code", read_only=True)
    normal_min = serializers.DecimalField(
        source="indicator.normal_min", max_digits=10, decimal_places=3, read_only=True
    )
    normal_max = serializers.DecimalField(
        source="indicator.normal_max", max_digits=10, decimal_places=3, read_only=True
    )

    class Meta:
        model = AnalysisResultValue
        fields = [
            "id",
            "indicator",
            "indicator_name",
            "indicator_code",
            "indicator_unit",
            "value",
            "is_abnormal",
            "normal_min",
            "normal_max",
        ]
        read_only_fields = ["id", "is_abnormal"]

class AnalysisResultSerializer(serializers.ModelSerializer):
    values = AnalysisResultValueSerializer(many=True, read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisResult
        fields = [
            "id",
            "file_key",
            "file_mime",
            "file_url",
            "patient_note",
            "submitted_at",
            "values",
        ]
        read_only_fields = ["id", "submitted_at"]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_file_url(self, obj):
        return _signed_download(obj.file_key)

class AnalysisFileSerializer(serializers.ModelSerializer):
    """Analizga ilova qilingan fayl (rasm/PDF)."""

    file_url = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisFile
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


# --- Analiz asosiy ---

class AnalysisListSerializer(serializers.ModelSerializer):
    """Yengil list serializer (qisqa kartochka uchun)."""

    type_name = serializers.CharField(source="type.name", read_only=True)
    type_icon = serializers.CharField(source="type.icon", read_only=True)
    type_code = serializers.CharField(source="type.code", read_only=True)
    type_category = serializers.CharField(source="type.category", read_only=True)
    doctor_name = serializers.CharField(source="doctor.full_name", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    days_left = serializers.SerializerMethodField()
    indicator_names = serializers.SerializerMethodField()
    ui_status = serializers.SerializerMethodField()
    files_count = serializers.SerializerMethodField()
    verdict_preview = serializers.SerializerMethodField()
    display_title = serializers.SerializerMethodField()

    class Meta:
        model = Analysis
        fields = [
            "id",
            "type",
            "type_name",
            "type_icon",
            "type_code",
            "type_category",
            "patient",
            "patient_name",
            "doctor",
            "doctor_name",
            "source",
            "source_display",
            "title",
            "display_title",
            "recorded_at",
            "status",
            "status_display",
            "ui_status",
            "deadline_at",
            "days_left",
            "verdict",
            "verdict_preview",
            "submitted_at",
            "reviewed_at",
            "doctor_viewed_at",
            "created_at",
            "indicator_names",
            "custom_indicators",
            "custom_preparations",
            "files_count",
        ]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_days_left(self, obj):
        return _days_left(obj)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_indicator_names(self, obj):
        return list(obj.indicators.values_list("name", flat=True))

    @extend_schema_field(serializers.CharField())
    def get_ui_status(self, obj):
        return _compute_ui_status(obj)

    @extend_schema_field(serializers.IntegerField())
    def get_files_count(self, obj):
        # prefetch ishlatilgani uchun .all() Python-side hisoblanadi
        return len(obj.files.all())

    @extend_schema_field(serializers.CharField())
    def get_verdict_preview(self, obj):
        if not obj.verdict:
            return ""
        text = obj.verdict.strip()
        return text if len(text) <= 120 else text[:117] + "..."

    @extend_schema_field(serializers.CharField())
    def get_display_title(self, obj):
        # type.name JSONField — pick_for context'dan til oladi
        if obj.title:
            return obj.title
        if obj.type_id:
            return pick_for(self.context, obj.type.name)
        return ""

class _RecipientDoctorBriefSerializer(serializers.Serializer):
    """Detail'da `recipients` (kimga yuborilgan) uchun qisqa info."""

    doctor_profile_id = serializers.IntegerField()
    user_id = serializers.IntegerField()
    full_name = serializers.CharField()
    specialty = serializers.CharField(allow_null=True)
    avatar_url = serializers.URLField(allow_null=True)

class _AnalysisDoctorBriefSerializer(serializers.Serializer):
    """Sharh yozgan doctor uchun qisqa info — detail kartochkadagi avatar/ism/ixtisos."""

    user_id = serializers.IntegerField(allow_null=True)
    doctor_profile_id = serializers.IntegerField(allow_null=True)
    full_name = serializers.CharField(allow_null=True)
    specialty = serializers.CharField(allow_null=True)
    avatar_url = serializers.URLField(allow_null=True)

class AnalysisDetailSerializer(serializers.ModelSerializer):
    """Detail — indicators, preparations, files, recipients, doctor bilan to'liq."""

    type_name = serializers.CharField(source="type.name", read_only=True)
    type_icon = serializers.CharField(source="type.icon", read_only=True)
    type_code = serializers.CharField(source="type.code", read_only=True)
    type_category = serializers.CharField(source="type.category", read_only=True)
    doctor_name = serializers.CharField(source="doctor.full_name", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    indicators_detail = AnalysisIndicatorSerializer(
        source="indicators", many=True, read_only=True
    )
    preparations_detail = AnalysisPreparationSerializer(
        source="preparations", many=True, read_only=True
    )
    result = AnalysisResultSerializer(read_only=True)
    files = AnalysisFileSerializer(many=True, read_only=True)
    days_left = serializers.SerializerMethodField(allow_null=True)
    ui_status = serializers.SerializerMethodField()
    display_title = serializers.SerializerMethodField()
    doctor_brief = serializers.SerializerMethodField()
    recipients_detail = serializers.SerializerMethodField()
    total_size_bytes = serializers.SerializerMethodField()

    class Meta:
        model = Analysis
        fields = [
            "id",
            "patient",
            "patient_name",
            "doctor",
            "doctor_name",
            "doctor_brief",
            "type",
            "type_name",
            "type_icon",
            "type_code",
            "type_category",
            "source",
            "source_display",
            "title",
            "display_title",
            "recorded_at",
            "indicators",
            "indicators_detail",
            "custom_indicators",
            "preparations",
            "preparations_detail",
            "custom_preparations",
            "recipients",
            "recipients_detail",
            "deadline_at",
            "days_left",
            "status",
            "status_display",
            "ui_status",
            "note",
            "verdict",
            "cancelled_reason",
            "cancelled_at",
            "submitted_at",
            "reviewed_at",
            "doctor_viewed_at",
            "result",
            "files",
            "total_size_bytes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "patient",
            "doctor",
            "source",
            "status",
            "verdict",
            "cancelled_reason",
            "cancelled_at",
            "submitted_at",
            "reviewed_at",
            "doctor_viewed_at",
            "result",
            "files",
            "recipients",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_days_left(self, obj):
        return _days_left(obj)

    @extend_schema_field(serializers.CharField())
    def get_ui_status(self, obj):
        return _compute_ui_status(obj)

    @extend_schema_field(serializers.CharField())
    def get_display_title(self, obj):
        # type.name JSONField — pick_for context'dan til oladi
        if obj.title:
            return obj.title
        if obj.type_id:
            return pick_for(self.context, obj.type.name)
        return ""

    @extend_schema_field(_AnalysisDoctorBriefSerializer(allow_null=True))
    def get_doctor_brief(self, obj):
        return _doctor_brief(obj.doctor) if obj.doctor_id else None

    @extend_schema_field(_RecipientDoctorBriefSerializer(many=True))
    def get_recipients_detail(self, obj):
        items = []
        for dp in obj.recipients.all().select_related("user", "specialty"):
            u = dp.user
            items.append(
                {
                    "doctor_profile_id": dp.id,
                    "user_id": u.id,
                    "full_name": u.full_name or u.phone,
                    "specialty": dp.specialty.name if dp.specialty_id else None,
                    "avatar_url": _signed_download(u.avatar),
                }
            )
        return items

    @extend_schema_field(serializers.IntegerField())
    def get_total_size_bytes(self, obj):
        return sum((f.file_size_bytes or 0) for f in obj.files.all())
