from rest_framework import serializers

from core.serializers import TranslatableFieldsMixin

from .models import MobileAppInfo


class MobileAppInfoSerializer(TranslatableFieldsMixin, serializers.ModelSerializer):
    """`title`/`message` 3 tilli. O'qish: `?lang=` → string; `?include_translations=1`
    (admin) → dict. Yozish (admin): dict."""

    translatable_fields = ["title", "message"]

    class Meta:
        model = MobileAppInfo
        fields = [
            "id",
            "app_scope",
            "latest_version",
            "min_version",
            "update_available",
            "force_update",
            "title",
            "message",
            "ios_url",
            "android_url",
            "is_active",
            "updated_at",
        ]
        # app_scope — fiksatsiya (patient/doctor qatorlari oldindan mavjud).
        read_only_fields = ["id", "app_scope", "updated_at"]
