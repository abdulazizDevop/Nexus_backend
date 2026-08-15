from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar


@extend_schema(tags=["Medical - Shifokor yozuvlari"])
class MedicalNoteViewSet(viewsets.ModelViewSet):
    """Shifokor yozuvlari (kunlik kuzatuv).

    Filter:
        ?patient_id=5    — bemor ID (doctor uchun)
    """

    serializer_class = MedicalNoteSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head"]
    queryset = MedicalNote.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MedicalNote.objects.none()

        request = self.request
        user = request.user
        base = MedicalNote.objects.select_related("created_by").prefetch_related(
            "images"
        )
        role = get_request_role(request)

        # Detail action — patient_id query param shart emas.
        # Doctor uchun: o'zining accepted bemorlari yozuvlari ichidan izlaymiz.
        # Patient uchun: faqat o'z yozuvlari.
        if self.action in ("retrieve", "partial_update", "update", "destroy"):
            if role == "doctor":
                profile = getattr(user, "doctor_profile", None)
                if not profile:
                    return base.none()

                return base.filter(user_id__in=accepted_patient_ids(profile))
            return base.filter(user=user)

        # List — patient_id orqali filterlanadi (eski mantiq)
        patient_id = request.query_params.get("patient_id")
        if patient_id:
            target, err = resolve_target_user(request, patient_id)
            if err is not None or target is None:
                return base.none()
            return base.filter(user=target)

        return base.filter(user=user)

    @extend_schema(summary="Shifokor yozuvlari ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Yangi yozuv qo'shish")
    def create(self, request, *args, **kwargs):
        patient_id = request.data.get("patient_id")
        target, err = resolve_target_user(
            request, patient_id if patient_id else request.user.id
        )
        if err:
            return err

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=target, created_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Yozuvni yangilash (faqat o'zi yozgan doctor)")
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.created_by_id and instance.created_by_id != request.user.id:
            return Response(
                {"detail": "Faqat yozuv muallifi tahrirlay oladi."}, status=403
            )
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Yozuvni o'chirish")
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Faqat author yoki bemor o'zi
        if (
            instance.created_by_id
            and instance.created_by_id != request.user.id
            and instance.user_id != request.user.id
        ):
            return Response(
                {"detail": "Faqat yozuv muallifi yoki bemor o'chirishi mumkin."},
                status=403,
            )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(
        summary="Yozuvdan rasmni o'chirish (faqat muallif)",
        responses={204: None},
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=r"images/(?P<image_id>\d+)",
    )
    def delete_image(self, request, pk=None, image_id=None):
        note = self.get_object()
        if note.created_by_id and note.created_by_id != request.user.id:
            return Response(
                {"detail": "Faqat yozuv muallifi rasm o'chira oladi."}, status=403
            )
        deleted, _ = MedicalNoteImage.objects.filter(
            note=note, id=image_id
        ).delete()
        if not deleted:
            return Response({"detail": "Rasm topilmadi."}, status=404)
        return Response(status=204)


@extend_schema(tags=["Medical - Shifokor yozuvlari"])
class MedicalNoteImageUploadUrlView(APIView):
    """MedicalNote uchun rasm yuklash presigned URL'lari.

    Flow:
      1) POST bu endpoint → upload_url + file_key (count'ga ko'ra ko'p element)
      2) PUT {upload_url} bilan rasm S3 ga yuklanadi (15 daqiqa muddat)
      3) POST /medical/notes/ payloadiga `images_input: [{file_key, ...}]` qo'shiladi
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=MedicalNoteImageUploadUrlRequestSerializer,
        responses=MedicalNoteImageUploadUrlResponseSerializer,
        summary="Medical note rasm yuklash URL",
    )
    def post(self, request):
        serializer = MedicalNoteImageUploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_type = serializer.validated_data["file_type"]
        count = serializer.validated_data["count"]

        prefix = f"medical-notes/{request.user.id}/"
        items = [
            build_upload_item(prefix, file_type, fallback_ext="jpg")
            for _ in range(count)
        ]
        return Response({"items": items})


# --- AI STT (Speech-to-Text) uchun endpointlar ---


