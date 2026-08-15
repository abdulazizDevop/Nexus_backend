from .common import *  # noqa: F401,F403 - umumiy importlar (Decimal, serializers, modellar, TranslatableFieldsMixin)


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = ["id", "key", "value", "description", "updated_at"]
        read_only_fields = ["id", "updated_at"]

    def validate(self, attrs):
        # Doctor komissiyasi 0..100 oralig'ida bo'lishi shart. Aks holda
        # _create_tariff_purchase'da doctor_earnings manfiy bo'lib, balansni
        # buzadi yoki commission > price bo'lib doctor minus balans oladi.
        # Boshqa kalitlar uchun validatsiya yo'q (erkin JSON value).
        key = attrs.get("key") or (self.instance.key if self.instance else None)
        value = attrs.get("value")
        if key == "doctor_commission_percent" and value is not None:
            try:
                num = float(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"value": "Komissiya raqam bo'lishi shart."}
                )
            if num < 0 or num > 100:
                raise serializers.ValidationError(
                    {"value": "Komissiya 0 dan 100 gacha bo'lishi shart (foiz)."}
                )
        return attrs


# --- Pro ---
