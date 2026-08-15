from .common import *  # noqa: F401,F403 - umumiy importlar + _media_url + _TariffMixin
from .common import _TariffMixin,_media_url
from .specialty import SpecialtySerializer


class DoctorListSerializer(_TariffMixin, serializers.ModelSerializer):
    """Doctor ro'yxat — qisqa"""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    phone = serializers.CharField(source="user.phone", read_only=True)
    avatar = serializers.SerializerMethodField()
    specialty = SpecialtySerializer(read_only=True)
    specialties = SpecialtySerializer(many=True, read_only=True)
    rating = serializers.FloatField(read_only=True)
    total_patients = serializers.SerializerMethodField()
    is_online = serializers.BooleanField(read_only=True)
    tariff_status = serializers.SerializerMethodField()
    tariff_days_left = serializers.SerializerMethodField()
    tariff_expires_at = serializers.SerializerMethodField()
    tariff_name = serializers.SerializerMethodField()
    last_chat_at = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return _media_url(obj.user.avatar)

    @extend_schema_field(serializers.IntegerField())
    def get_total_patients(self, obj):
        # List view'da N+1 oldini olish — viewset precomputed xaritani contextga
        # uzatadi. Mavjud bo'lmasa property orqali fallback hisoblaymiz.
        m = self.context.get("total_patients_map")
        if m is not None:
            return m.get(obj.id, 0)
        return obj.total_patients

    def _purchase(self, obj):
        return (self.context.get("purchase_by_doctor") or {}).get(obj.id)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_chat_at(self, obj):
        return getattr(obj, "_last_chat_at", None)

    @extend_schema_field(serializers.IntegerField())
    def get_unread_count(self, obj):
        return getattr(obj, "_unread_count", 0) or 0

    class Meta:
        model = DoctorProfile
        fields = [
            "id",
            "user_id",
            "full_name",
            "phone",
            "avatar",
            "specialty",
            "specialties",
            "experience_years",
            "rating",
            "total_patients",
            "is_online",
            "is_verified",
            "tariff_status",
            "tariff_days_left",
            "tariff_expires_at",
            "tariff_name",
            "last_chat_at",
            "unread_count",
        ]


class MarketplaceDoctorSerializer(serializers.ModelSerializer):
    """Marketplace ('Barcha shifokorlar') kartasi — barcha maydonlar ANNOTATSIYADAN
    (N+1 yo'q). connection_status/has_active_tariff so'rovchi bemorga nisbatan."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    avatar = serializers.SerializerMethodField()
    specialties = SpecialtySerializer(many=True, read_only=True)
    rating = serializers.FloatField(read_only=True)
    reviews_count = serializers.SerializerMethodField()
    min_tariff_price = serializers.SerializerMethodField()
    connection_status = serializers.SerializerMethodField()
    has_active_tariff = serializers.SerializerMethodField()
    total_patients = serializers.SerializerMethodField()

    class Meta:
        model = DoctorProfile
        fields = [
            "id",
            "user_id",
            "full_name",
            "avatar",
            "specialties",
            "experience_years",
            "rating",
            "reviews_count",
            "is_verified",
            "min_tariff_price",
            "connection_status",
            "has_active_tariff",
            "total_patients",
            # Konsultatsiya — DoctorProfile ustunlari (select_related qatorida keladi,
            # N+1 yo'q). Default OFF: enabled=false, price=null bo'lib chiqadi.
            # Mobil Konsultatsiya tabini ko'rsatadi faqat: enabled=true VA status=approved.
            "consultation_enabled",
            "consultation_price",
            "consultation_duration_min",
            "consultation_status",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return _media_url(obj.user.avatar)

    @extend_schema_field(serializers.IntegerField())
    def get_reviews_count(self, obj):
        return getattr(obj, "_total_reviews", 0) or 0

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_min_tariff_price(self, obj):
        # Xom (chegirmasiz) minimal tarif narxi. Tarif yo'q → null ("Qabul yopiq").
        v = getattr(obj, "_min_tariff_price", None)
        return str(v) if v is not None else None

    @extend_schema_field(serializers.ChoiceField(choices=["none", "pending", "accepted"]))
    def get_connection_status(self, obj):
        s = getattr(obj, "_connection_status", None)
        # declined/None → 'none' (mobil enum: none/pending/accepted).
        return s if s in ("accepted", "pending") else "none"

    @extend_schema_field(serializers.BooleanField())
    def get_has_active_tariff(self, obj):
        return bool(getattr(obj, "_has_active_tariff", False))

    @extend_schema_field(serializers.IntegerField())
    def get_total_patients(self, obj):
        # DoctorListSerializer bilan bir xil naqsh: viewset butun sahifa uchun
        # precomputed xaritani contextga uzatadi (N+1 yo'q). Xarita bo'lmasa
        # property fallback (har karta uchun 2 so'rov — faqat map yo'q holatda).
        m = self.context.get("total_patients_map")
        if m is not None:
            return m.get(obj.id, 0)
        return obj.total_patients


# --- Doctor-Patient bog'lanish ---


