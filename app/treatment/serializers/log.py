from .common import *  # noqa: F401,F403


class TreatmentLogSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # PRN kontrakt: `taken_at` = qabul vaqti (completed_at aliasi).
    taken_at = serializers.DateTimeField(source="completed_at", read_only=True)

    class Meta:
        model = TreatmentLog
        fields = [
            "id",
            "treatment",
            "treatment_title",
            "treatment_type",
            "date",
            "status",
            "status_display",
            "completed_at",
            "taken_at",
            "scheduled_for",
        ]
        read_only_fields = [
            "id",
            "treatment_title",
            "treatment_type",
            "completed_at",
            "taken_at",
            "scheduled_for",
        ]


class TreatmentMarkSerializer(serializers.Serializer):
    """Muolajani bajarildi/o'tkazib yuborildi deb belgilash"""

    status = serializers.ChoiceField(choices=TreatmentLog.Status.choices)
    date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text="Default: bugun. O'tmish sanaga ruxsat yo'q.",
    )
    taken_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Qabul vaqti (ixtiyoriy). Berilmasa server now() ishlatadi. PRN uchun.",
    )
    scheduled_for = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text=(
            "Rejali dori uchun qaysi slot (vaqt) belgilanmoqda — slotning aniq "
            "wall-clock vaqti (offset bilan). Berilsa per-slot idempotent. PRN'da yuborilmaydi."
        ),
    )


class TreatmentStatsSerializer(serializers.Serializer):
    """Oylik statistika"""

    total = serializers.IntegerField()
    completed = serializers.IntegerField()
    skipped = serializers.IntegerField()
    completion_rate = serializers.IntegerField()
    streak = serializers.IntegerField()
