from .common import *  # noqa: F401,F403 - umumiy importlar + _media_url + _TariffMixin
from .common import _media_url
from .certificate import DoctorCertificateSerializer
from .specialty import SpecialtySerializer


class DoctorProfileSerializer(serializers.ModelSerializer):
    """Doctor profili — o'qish uchun"""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    avatar = serializers.SerializerMethodField()
    referral_code = serializers.CharField(source="user.referral_code", read_only=True)
    specialty = SpecialtySerializer(read_only=True)
    specialties = SpecialtySerializer(many=True, read_only=True)
    certificates = DoctorCertificateSerializer(many=True, read_only=True)
    rating = serializers.FloatField(read_only=True)
    total_patients = serializers.IntegerField(read_only=True)
    total_reviews = serializers.IntegerField(read_only=True)
    is_online = serializers.BooleanField(read_only=True)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return _media_url(obj.user.avatar)

    class Meta:
        model = DoctorProfile
        fields = [
            "id",
            "user_id",
            "full_name",
            "phone",
            "avatar",
            "referral_code",
            "specialty",
            "specialties",
            "bio",
            "experience_years",
            "license_number",
            "workplace",
            "commission_percent",
            "rating",
            "total_patients",
            "total_reviews",
            "is_online",
            "is_verified",
            "accepts_online",
            "accepts_offline",
            "consultation_enabled",
            "consultation_price",
            "consultation_duration_min",
            "consultation_status",
            "consultation_rejection_reason",
            "certificates",
            "created_at",
        ]


class DoctorProfileUpdateSerializer(serializers.ModelSerializer):
    """Doctor profili — yangilash uchun"""

    # Eski (bitta) yo'l — orqaga moslik uchun saqlanadi.
    specialty_id = serializers.PrimaryKeyRelatedField(
        queryset=Specialty.objects.all(),
        source="specialty",
        required=False,
        allow_null=True,
    )
    # Yangi — bir nechta mutaxassislik tanlash.
    specialty_ids = serializers.PrimaryKeyRelatedField(
        queryset=Specialty.objects.all(),
        source="specialties",
        many=True,
        required=False,
    )

    class Meta:
        model = DoctorProfile
        fields = [
            "specialty_id",
            "specialty_ids",
            "bio",
            "experience_years",
            "license_number",
            "workplace",
            "accepts_online",
            "accepts_offline",
            # Konsultatsiya sozlamasi — hammasi required=False (null/default bor),
            # shu sabab eski PATCH chaqiruvchilar (faqat bio/specialty) buzilmaydi.
            "consultation_enabled",
            "consultation_price",
            "consultation_duration_min",
        ]

    def validate(self, attrs):
        # partial=True — yakuniy holatni instance + kelayotgan attrs birlashmasidan
        # tekshiramiz: konsultatsiya YOQILGAN bo'lsa narx va davomiylik majburiy.
        inst = self.instance
        enabled = attrs.get(
            "consultation_enabled",
            inst.consultation_enabled if inst else False,
        )
        if enabled:
            price = attrs.get(
                "consultation_price", inst.consultation_price if inst else None
            )
            duration = attrs.get(
                "consultation_duration_min",
                inst.consultation_duration_min if inst else None,
            )
            if not price or price <= 0:
                raise serializers.ValidationError(
                    {"consultation_price": "Konsultatsiya yoqilganda narx > 0 bo'lishi shart."}
                )
            if not duration or duration <= 0:
                raise serializers.ValidationError(
                    {"consultation_duration_min": "Davomiylik > 0 bo'lishi shart."}
                )
        return attrs

    def update(self, instance, validated_data):
        # M2M ni super()'dan oldin ajratamiz (M2M instance saqlangach o'rnatiladi).
        specialties = validated_data.pop("specialties", "__unset__")
        single = validated_data.get("specialty", "__unset__")
        instance = super().update(instance, validated_data)

        if specialties != "__unset__":
            # `specialty_ids` berilgan — M2M o'rnatiladi, asosiy = birinchisi
            # (users/medical/meetings/AI barcha `.specialty` o'quvchilari uchun).
            instance.specialties.set(specialties)
            primary = specialties[0] if specialties else None
            if instance.specialty_id != (primary.id if primary else None):
                instance.specialty = primary
                instance.save(update_fields=["specialty"])
        elif single != "__unset__":
            # Faqat eski `specialty_id` berilgan — M2M ni ham sinxronlaymiz.
            instance.specialties.set([single] if single else [])
        return instance


