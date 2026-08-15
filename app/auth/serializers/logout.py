from .common import *  # noqa: F401,F403


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    device_token = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            "Ixtiyoriy: shu device'ning push tokeni. Yuborilsa — DeviceToken "
            "deactivate qilinadi (logout qilgan device'ga keyingi push'lar "
            "yuborilmaydi)."
        ),
    )
