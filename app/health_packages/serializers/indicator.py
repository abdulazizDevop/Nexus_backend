from .common import *  # noqa: F401,F403
from .common import _validate_not_future  # underscore (star bermaydi)


class HealthIndicatorTypeSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """Ko'rsatkich turi — `name` 3 tilli JSON.

    O'qish:
      - `?lang=ru` → `name: "Вес"` (string)
      - `?include_translations=1` (admin) → `name: {uz, ru, cyr}` (dict)

    `system_key`:
      - Patient/Doctor uchun null (oddiy tur — qo'lda kiritiladi)
      - Admin tomonidan tizim turi yaratilsa, set qilinadi (masalan Diet AI
        macros). Bir marta belgilangach o'zgartirilmaydi
        (frontend kod bilan bog'langan stable ID).
    """

    translatable_fields = ["name"]

    class Meta:
        model = HealthIndicatorType
        fields = [
            "id", "name", "system_key", "unit", "icon", "value_format",
            "category", "manual_entry",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "system_key": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
                "help_text": (
                    "Stable identifier (masalan: 'heart_rate', 'weight'). "
                    "Faqat admin tizim turi yaratganda beriladi. "
                    "Bir marta belgilangach o'zgartirib bo'lmaydi."
                ),
            },
        }

    def validate_system_key(self, value):
        # bo'sh string → null
        if not value:
            return None

        # Mavjud yozuvda system_key o'zgartirib bo'lmaydi
        if self.instance and self.instance.system_key and self.instance.system_key != value:
            raise serializers.ValidationError(
                f"system_key o'zgartirib bo'lmaydi (mavjud: '{self.instance.system_key}'). "
                "Bu frontend kodi bilan bog'langan stable identifier."
            )

        # Unique tekshiruv
        qs = HealthIndicatorType.objects.filter(system_key=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"'{value}' system_key allaqachon ishlatilgan."
            )

        return value

    def validate(self, attrs):
        # SYSTEM_NAMES (Kaloriya/Uglevod/Oqsil/Yog') reservation —
        # faqat oddiy turlari uchun (system_key yo'q bo'lsa). Admin ataylab
        # tizim turi yaratsa (system_key bilan), bu nomlardan foydalanishi mumkin.
        system_key = attrs.get("system_key")
        if "system_key" not in attrs and self.instance:
            system_key = self.instance.system_key

        if not system_key:
            name = attrs.get("name") or (self.instance.name if self.instance else None)
            if name:
                check = name.get("uz") if isinstance(name, dict) else name
                if check in HealthIndicatorType.SYSTEM_NAMES:
                    raise serializers.ValidationError({
                        "name": (
                            "Bu nom Diet AI tomonidan ishlatiladigan tizim turlari uchun "
                            "zaxiralangan. Tizim turi qo'shmoqchi bo'lsangiz system_key bering."
                        )
                    })

        return attrs


class HealthIndicatorSerializer(serializers.ModelSerializer):
    indicator_type_detail = HealthIndicatorTypeSerializer(
        source="indicator_type", read_only=True
    )
    # Top-level system_key — multi-metric (`?metrics=`) javobida client har element
    # qaysi metric'ga tegishli ekanini ajratishi uchun (single'da ham zararsiz).
    metric = serializers.CharField(
        source="indicator_type.system_key", read_only=True
    )
    display_value = serializers.CharField(read_only=True)
    patient_profile_id = serializers.IntegerField(read_only=True)
    value = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    value_secondary = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True
    )

    def validate_recorded_at(self, value):
        return _validate_not_future(value)

    class Meta:
        model = HealthIndicator
        fields = [
            "id",
            "user",  # User.id (legacy)
            "patient_profile_id",  # Patient.id (yangi)
            "metric",  # indicator_type.system_key (multi-metric javob uchun)
            "indicator_type",
            "indicator_type_detail",
            "value",
            "value_secondary",
            "display_value",
            "recorded_at",
            "date",
            "source",
            "meta",
        ]
        read_only_fields = [
            "id", "user", "patient_profile_id", "display_value", "date", "source",
        ]

    def validate(self, attrs):
        indicator_type = attrs.get("indicator_type") or (
            self.instance.indicator_type if self.instance else None
        )
        value_secondary = attrs.get("value_secondary")

        if not indicator_type:
            return attrs

        # Barcha turlarga qo'lda qiymat kiritishga ruxsat — system_key bor turlar
        # (Diet AI macros va boshqa tizim turlari) ham qo'lda kiritilishi mumkin.
        if indicator_type.value_format == HealthIndicatorType.ValueFormat.RANGE:
            if value_secondary is None:
                # JSONField name'ni xato matnida user tilida ko'rsatish
                name_str = pick_for(self.context, indicator_type.name)
                raise serializers.ValidationError(
                    {
                        "value_secondary": (
                            f"'{name_str}' uchun ikkinchi qiymat majburiy "
                            f"(masalan: 120/80 → value=120, value_secondary=80)."
                        )
                    }
                )
        else:
            # number formatda secondary bo'lmasligi kerak
            if value_secondary is not None:
                attrs["value_secondary"] = None

        return attrs
