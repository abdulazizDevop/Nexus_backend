from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from app.doctors.models import DoctorProfile
from core.i18n import pick_for
from services.storage import generate_download_url

from .models import Appointment, Consultation


def _avatar_url(key):
    """S3 key ni Bunny CDN signed URL ga aylantiradi."""
    return generate_download_url(key) if key else None


def _doctor_specialty(obj, context):
    """Doctor.specialty.name JSONField'idan so'rov tiliga mos qiymat olish."""
    if not obj.doctor or not obj.doctor.specialty:
        return None
    return pick_for(context, obj.doctor.specialty.name)


class AppointmentCreateSerializer(serializers.ModelSerializer):
    """Patient — uchrashuv so'rovi yuborish.

    Slot lookup va atomic free→booked tranzitsiya viewset'da bajariladi.
    Bu serializer faqat oddiy format/business validatsiyani qiladi.
    """

    doctor_id = serializers.PrimaryKeyRelatedField(
        queryset=DoctorProfile.objects.filter(user__is_active=True),
        source="doctor",
        error_messages={
            "does_not_exist": "Shifokor topilmadi. Iltimos, doctor_id ni tekshiring.",
            "incorrect_type": "doctor_id raqam bo'lishi kerak.",
        },
    )

    class Meta:
        model = Appointment
        fields = [
            "doctor_id",
            "date",
            "start_time",
            "end_time",
            "meeting_type",
            "reason",
        ]

    def validate(self, data):
        doctor = data["doctor"]
        date = data["date"]
        start = data["start_time"]
        end = data["end_time"]
        meeting_type = data["meeting_type"]

        if start >= end:
            raise serializers.ValidationError(
                {"end_time": "Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak."}
            )

        if not doctor.is_verified:
            raise serializers.ValidationError(
                {
                    "doctor_id": (
                        "Bu shifokor hali tasdiqlanmagan. "
                        "Faqat tasdiqlangan shifokorlarga yozilish mumkin."
                    )
                }
            )

        if date < timezone.localdate():
            raise serializers.ValidationError(
                {"date": "O'tgan sanaga uchrashuv belgilash mumkin emas."}
            )

        if meeting_type == Appointment.MeetingType.ONLINE and not doctor.accepts_online:
            raise serializers.ValidationError(
                {"meeting_type": "Bu doctor online qabul qilmaydi."}
            )
        if meeting_type == Appointment.MeetingType.OFFLINE and not doctor.accepts_offline:
            raise serializers.ValidationError(
                {"meeting_type": "Bu doctor offline qabul qilmaydi."}
            )

        return data


class _AppointmentSerializerBase(serializers.ModelSerializer):
    """List + Detail uchun umumiy maydonlar."""

    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_avatar = serializers.SerializerMethodField()
    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_name = serializers.CharField(source="doctor.user.full_name", read_only=True)
    doctor_avatar = serializers.SerializerMethodField()
    doctor_specialty = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_patient_avatar(self, obj):
        return _avatar_url(obj.patient.avatar) if obj.patient else None

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_doctor_avatar(self, obj):
        return _avatar_url(obj.doctor.user.avatar) if obj.doctor else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_doctor_specialty(self, obj):
        return _doctor_specialty(obj, self.context)


class AppointmentListSerializer(_AppointmentSerializerBase):
    """Uchrashuv ro'yxati — qisqa"""

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_profile_id",
            "patient_name",
            "patient_avatar",
            "doctor",
            "doctor_name",
            "doctor_avatar",
            "doctor_specialty",
            "date",
            "start_time",
            "end_time",
            "meeting_type",
            "status",
            "reason",
            "reject_reason",
            "notes",
            "cancelled_by",
            "created_at",
        ]


class AppointmentDetailSerializer(_AppointmentSerializerBase):
    """Uchrashuv batafsil"""

    patient_phone = serializers.CharField(source="patient.phone", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_profile_id",
            "patient_name",
            "patient_phone",
            "patient_avatar",
            "doctor",
            "doctor_name",
            "doctor_specialty",
            "doctor_avatar",
            "date",
            "start_time",
            "end_time",
            "meeting_type",
            "status",
            "reason",
            "reject_reason",
            "notes",
            "room_name",
            "cancelled_by",
            "created_at",
            "updated_at",
        ]


class AppointmentApproveSerializer(serializers.Serializer):
    """Doctor — tasdiqlash"""

    notes = serializers.CharField(required=False, allow_blank=True, default="")


class AppointmentRejectSerializer(serializers.Serializer):
    """Doctor — rad etish"""

    reject_reason = serializers.CharField()


class AppointmentCancelSerializer(serializers.Serializer):
    """Patient/Doctor — bekor qilish"""

    reason = serializers.CharField(required=False, allow_blank=True, default="")


# ============================================================
# Konsultatsiya (bir martalik pullik video-qabul)
# ============================================================


class ConsultationBookSerializer(serializers.Serializer):
    """Booking so'rovi: doctor + slot (sana+vaqt) + to'lov provayderi."""

    doctor_id = serializers.IntegerField()
    date = serializers.DateField()
    time = serializers.TimeField(help_text="Slot boshlanish vaqti, HH:MM")
    # MVP: Payme/Click redirect (to'liq ishlaydi). ATMOS saqlangan-karta (OTP) va
    # naqd keyingi bosqich — webhook confirm tomoni allaqachon provider-agnostik.
    provider = serializers.ChoiceField(choices=["payme", "click"])


class ConsultationSlotSerializer(serializers.Serializer):
    """Bo'sh/band slot vitrinasi: {time, available}."""

    time = serializers.CharField(help_text="HH:MM")
    available = serializers.BooleanField()


class ConsultationSerializer(serializers.ModelSerializer):
    """Konsultatsiya — bemor VA shifokor tomoni uchun yagona serializer.

    Bemor app `doctor_*`, doctor app `patient_*` maydonlarini oladi. Hamma
    maydon additive — eski app'lar yangi kalitlarni e'tiborsiz qoldiradi.
    """

    doctor_id = serializers.IntegerField(source="doctor.id", read_only=True)
    doctor_name = serializers.CharField(
        source="doctor.user.full_name", read_only=True
    )
    doctor_avatar = serializers.SerializerMethodField()
    doctor_specialty = serializers.SerializerMethodField()
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)
    patient_name = serializers.CharField(
        source="patient.full_name", read_only=True
    )
    patient_avatar = serializers.SerializerMethodField()
    patient_gender = serializers.CharField(
        source="patient.sex", read_only=True, allow_null=True
    )
    patient_birth_date = serializers.DateField(
        source="patient.birth_date", read_only=True, allow_null=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )

    class Meta:
        model = Consultation
        fields = [
            "id",
            "doctor_id",
            "doctor_name",
            "doctor_avatar",
            "doctor_specialty",
            "patient_id",
            "patient_name",
            "patient_avatar",
            "patient_gender",
            "patient_birth_date",
            "date",
            "start_time",
            "end_time",
            "status",
            "status_display",
            "amount",
            "room_name",
            "created_at",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_doctor_avatar(self, obj):
        key = obj.doctor.user.avatar
        return generate_download_url(key) if key else None

    def get_doctor_specialty(self, obj):
        return _doctor_specialty(obj, self.context)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_patient_avatar(self, obj):
        return _avatar_url(obj.patient.avatar)


class ConsultationBookResponseSerializer(serializers.Serializer):
    """POST booking javobi."""

    booking_id = serializers.IntegerField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_url = serializers.CharField(allow_null=True)
