from .common import *  # noqa: F401,F403 - umumiy importlar + _media_url + _TariffMixin


class _SlotStatusFieldsMixin:
    """Status-conditional field pruning Slot serializerlari uchun.

    - status != BOOKED  → appointment maydonini (`_appointment_field`) olib tashlaydi
    - status != BLOCKED → `reason` ni olib tashlaydi

    Subclass `_appointment_field` atributini belgilasin (`appointment_id` yoki
    `appointment`).
    """

    _appointment_field = "appointment_id"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.status != Slot.Status.BOOKED:
            data.pop(self._appointment_field, None)
        if instance.status != Slot.Status.BLOCKED:
            data.pop("reason", None)
        return data


class SlotSerializer(_SlotStatusFieldsMixin, serializers.ModelSerializer):
    """Slot — output. HH:MM format, status-conditional fields.

    - `free` → faqat id, date, times, status
    - `booked` → + appointment_id
    - `blocked` → + reason
    """

    start_time = serializers.TimeField(format="%H:%M", read_only=True)
    end_time = serializers.TimeField(format="%H:%M", read_only=True)
    appointment_id = serializers.IntegerField(read_only=True, allow_null=True)

    _appointment_field = "appointment_id"

    class Meta:
        model = Slot
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "status",
            "appointment_id",
            "reason",
        ]
        read_only_fields = fields


class AdminSlotSerializer(_SlotStatusFieldsMixin, serializers.ModelSerializer):
    """Admin uchun slot — booked bo'lsa appointment ma'lumotlari nested.

    Slot.Status faqat 3 ta (free/booked/blocked), lekin admin booked slot orqali
    appointment.status (pending/approved/completed) ni ham ko'rishi kerak.
    """

    start_time = serializers.TimeField(format="%H:%M", read_only=True)
    end_time = serializers.TimeField(format="%H:%M", read_only=True)
    appointment = serializers.SerializerMethodField()

    _appointment_field = "appointment"

    class Meta:
        model = Slot
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "status",
            "appointment",
            "reason",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_appointment(self, obj):
        if obj.status != Slot.Status.BOOKED or not obj.appointment_id:
            return None
        appt = obj.appointment
        return {
            "id": appt.id,
            "status": appt.status,
            "status_display": appt.get_status_display(),
            "patient_id": appt.patient_id,
            "patient_name": appt.patient.full_name if appt.patient else None,
            "meeting_type": appt.meeting_type,
        }


class SlotCreateItemSerializer(serializers.Serializer):
    """Sync request ichidagi `create` element."""

    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    status = serializers.ChoiceField(
        choices=[Slot.Status.FREE, Slot.Status.BLOCKED],
        required=False,
        default=Slot.Status.FREE,
    )
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class SlotUpdateItemSerializer(serializers.Serializer):
    """Sync request ichidagi `update` element. PATCH semantikasi."""

    id = serializers.IntegerField()
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    status = serializers.ChoiceField(
        choices=[Slot.Status.FREE, Slot.Status.BLOCKED],
        required=False,
    )
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )


class SlotSyncRequestSerializer(serializers.Serializer):
    """Atomic batch save: create + update + delete."""

    create = SlotCreateItemSerializer(many=True, required=False, default=list)
    update = SlotUpdateItemSerializer(many=True, required=False, default=list)
    delete = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


