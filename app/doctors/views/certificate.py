from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar + helperlar


# --- Sertifikatlar ---


@extend_schema(tags=["Doctor - Sertifikatlar"])
class DoctorCertificateViewSet(viewsets.ModelViewSet):
    """Doctor sertifikatlari va mukofotlari"""

    serializer_class = DoctorCertificateSerializer
    permission_classes = [IsDoctor]
    parser_classes = [MultiPartParser, JSONParser]

    def get_queryset(self):
        profile = getattr(self.request.user, "doctor_profile", None)
        if profile:
            return DoctorCertificate.objects.filter(doctor=profile)
        return DoctorCertificate.objects.none()

    def perform_create(self, serializer):
        profile, _ = DoctorProfile.objects.get_or_create(user=self.request.user)
        serializer.save(doctor=profile)

    @extend_schema(summary="Sertifikatlar ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Sertifikat qo'shish")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(summary="Sertifikatni o'chirish")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(
        summary="Sertifikat yuklash uchun presigned URL",
        description="file_name va file_type yuboriladi. upload_url ga PUT qilib fayl yuklanadi.",
    )
    @action(detail=False, methods=["post"], url_path="upload-url")
    def upload_url(self, request):
        file_name = request.data.get("file_name", "cert.jpg")
        file_type = request.data.get("file_type", "image/jpeg")
        file_size = request.data.get("file_size")

        # Sertifikat uchun maksimal 10MB (rasm yoki PDF) — abuse va S3 cost'dan himoya
        MAX_CERT_BYTES = 10 * 1024 * 1024
        try:
            file_size_int = int(file_size) if file_size is not None else None
        except (TypeError, ValueError):
            return Response({"detail": "file_size noto'g'ri."}, status=400)
        if file_size_int is not None and file_size_int > MAX_CERT_BYTES:
            return Response(
                {"detail": "Sertifikat 10MB dan oshmasligi kerak."}, status=400
            )

        allowed = ("image/jpeg", "image/png", "image/webp", "application/pdf")
        if file_type not in allowed:
            return Response(
                {"detail": f"Faqat {', '.join(allowed)} ruxsat etilgan"}, status=400
            )

        profile = getattr(request.user, "doctor_profile", None)
        if not profile:
            return Response({"detail": "Doctor profili topilmadi"}, status=400)

        file_key = generate_certificate_key(profile.id, file_name)
        url = generate_upload_url(file_key, file_type)

        return Response(
            {
                "upload_url": url,
                "file_key": file_key,
                "expires_in": 900,
            }
        )


# --- Slotlar ---


