from .common import *  # noqa: F401,F403 - umumiy importlar + _media_url + _TariffMixin
from .common import _media_url


class DoctorCertificateSerializer(serializers.ModelSerializer):
    """Sertifikat serializer.

    - **POST/PATCH** (write): `image` — S3 key (masalan `'certificates/5/abc.pdf'`).
      Mobile `/upload-url` chaqirib `file_key` oladi, S3'ga PUT qiladi, keyin
      shu key'ni `image` deb yuboradi.
    - **GET** (read): `image_url` — Bunny CDN signed URL (frontend ko'rsatish uchun).
      `image` field read'da S3 key ko'rinishida qaytadi (debug/admin uchun).

    Avval `image` SerializerMethodField (read-only) edi — mobile POST'da kelgan
    qiymat e'tibordan tushardi, DB'da image=null bo'lib qolardi.
    """

    image_url = serializers.SerializerMethodField()

    class Meta:
        model = DoctorCertificate
        fields = ["id", "title", "issuer", "year", "image", "image_url"]

    def validate_image(self, value):
        # XAVFSIZLIK: image key FAQAT o'z sertifikat prefiksida bo'lsin — client
        # ixtiyoriy S3 key (chat fayli, boshqa doctor sertifikati...) berib
        # imzolangan URL oldira olmasin (IDOR). Upload certificates/{profile.id}/ beradi.
        if not value:
            return value
        request = self.context.get("request")
        profile = getattr(getattr(request, "user", None), "doctor_profile", None)
        pid = getattr(profile, "id", None)
        if pid is None or not str(value).startswith(f"certificates/{pid}/"):
            raise serializers.ValidationError("Noto'g'ri sertifikat rasmi key.")
        return value

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return _media_url(obj.image)


