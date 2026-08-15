from .common import *  # noqa: F401,F403


class LinkDoctorSerializer(serializers.Serializer):
    referral_code = serializers.CharField(max_length=8)

    def validate_referral_code(self, value):
        if not User.objects.filter(referral_code=value, role="doctor").exists():
            raise serializers.ValidationError("Noto'g'ri doctor referral code.")
        return value
