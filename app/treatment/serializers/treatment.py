from .common import *  # noqa: F401,F403
from .common import _validate_doctor_patient_link  # underscore (star bermaydi)


def _normalize_times(value):
    """["08:00", "12:00", ...] → tartiblangan, takrorsiz ["08:00:00", ...] (validatsiya bilan)."""
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise serializers.ValidationError("times ro'yxat bo'lishi kerak.")
    tf = serializers.TimeField()
    seen, result = set(), []
    for raw in value:
        try:
            t = tf.to_internal_value(raw)
        except serializers.ValidationError:
            raise serializers.ValidationError(f"Noto'g'ri vaqt format: {raw}")
        key = t.strftime("%H:%M:%S")
        if key not in seen:
            seen.add(key)
            result.append(key)
    return sorted(result)


class TreatmentSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    repeat_display = serializers.CharField(source="get_repeat_display", read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    scheduled_times = serializers.ListField(
        child=serializers.TimeField(), source="get_scheduled_times", read_only=True
    )
    times = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Aniq qabul vaqtlari: ["08:00", "12:00", "19:00"]. Multi-slot manbai.',
    )
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default=None
    )
    today_status = serializers.SerializerMethodField()
    today_completed_count = serializers.SerializerMethodField()
    today_all_done = serializers.SerializerMethodField()

    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Treatment
        fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "type",
            "type_display",
            "status",
            "status_display",
            "title",
            "dosage",
            "duration",
            "time",
            "end_time",
            "interval_hours",
            "times",
            "repeat",
            "repeat_display",
            "custom_days",
            "end_date",
            "notes",
            "is_as_needed",
            "as_needed_reason",
            "max_per_day",
            "min_interval_hours",
            "is_active",
            "scheduled_times",
            "today_status",
            "today_completed_count",
            "today_all_done",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "patient_profile_id",
            "doctor_profile_id",
            "is_active",
            "scheduled_times",
            "today_status",
            "today_completed_count",
            "today_all_done",
            "created_by_name",
            "created_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_today_status(self, obj):
        """Bugungi log holati: completed, skipped, yoki null (hali bajarilmagan)"""
        # Prefetch qilingan today_logs mavjud bo'lsa
        if hasattr(obj, "today_logs"):
            if obj.today_logs:
                return obj.today_logs[0].status
            return None

        log = obj.logs.filter(date=timezone.localdate()).first()
        return log.status if log else None

    @extend_schema_field(serializers.IntegerField())
    def get_today_completed_count(self, obj):
        """Bugun 'completed' bo'lgan slotlar soni (per-slot log) — numerator (N/M dagi N).

        Maxraj (M) mobil tomonda `scheduled_times` uzunligi. Prefetch qilingan
        `today_logs` bo'lsa N+1 yo'q; PRN'da scheduled_times=[] → mobil "N marta" ko'rsatadi.
        """
        if hasattr(obj, "today_logs"):
            return sum(1 for lg in obj.today_logs if lg.status == "completed")
        return obj.logs.filter(
            date=timezone.localdate(), status="completed"
        ).count()

    @extend_schema_field(serializers.BooleanField())
    def get_today_all_done(self, obj):
        """Bugun HAMMA slot bajarildimi (per-doza). Doctor/UI 'Bajarilgan' badge shu maydon
        bo'yicha bo'lsin — `today_status` (binary, birinchi slot) EMAS.

        Rejali: bajarilgan slotlar >= rejalashtirilgan slotlar. PRN/jadvalsiz: bugun
        kamida bitta completed log bo'lsa True.
        """
        completed = self.get_today_completed_count(obj)
        scheduled = obj.get_scheduled_times()
        if scheduled:
            return completed >= len(scheduled)
        return completed > 0

    def validate_times(self, value):
        return _normalize_times(value)

    def validate(self, data):
        # PRN ("kerak bo'lganda") — jadval maydonlari (time/repeat/interval) kerak
        # emas, shuning uchun jadval validatsiyalari o'tkazib yuboriladi.
        if data.get("is_as_needed"):
            return data
        if data.get("repeat") == "custom" and not data.get("custom_days"):
            raise serializers.ValidationError(
                {
                    "custom_days": "repeat=custom bo'lsa hafta kunlari majburiy (masalan: '1,3,5')"
                }
            )
        # `times` berilsa — u asosiy manba, interval_hours/end_time talab qilinmaydi.
        if (
            not data.get("times")
            and data.get("interval_hours")
            and not data.get("end_time")
        ):
            raise serializers.ValidationError(
                {"end_time": "interval_hours bo'lsa end_time majburiy."}
            )
        return data


class DoctorTreatmentCreateSerializer(serializers.ModelSerializer):
    """Doctor bemorga muolaja yozish"""

    patient_id = serializers.IntegerField(write_only=True)
    times = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text='Aniq qabul vaqtlari: ["08:00", "12:00", "19:00"]. Multi-slot manbai.',
    )

    class Meta:
        model = Treatment
        fields = [
            "patient_id",
            "type",
            "title",
            "dosage",
            "duration",
            "time",
            "end_time",
            "interval_hours",
            "times",
            "repeat",
            "custom_days",
            "end_date",
            "notes",
            "is_as_needed",
            "as_needed_reason",
            "max_per_day",
            "min_interval_hours",
        ]

    def validate_patient_id(self, value):
        return _validate_doctor_patient_link(value, self.context)

    def validate_times(self, value):
        return _normalize_times(value)
