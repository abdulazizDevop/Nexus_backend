from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar


@extend_schema(tags=["Medical - Kasalliklar / Allergiyalar"])
class MedicalConditionViewSet(viewsets.ModelViewSet):
    """Kasallik / allergiya / operatsiya / vaksina yozuvlari.

    Filter:
        ?patient_id=5    — doctor uchun (bemor ID)
        ?type=allergy    — kasallik turi bo'yicha
    """

    serializer_class = MedicalConditionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head"]
    queryset = MedicalCondition.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MedicalCondition.objects.none()

        request = self.request
        user = request.user
        base = MedicalCondition.objects.select_related("added_by")
        role = get_request_role(request)

        # Detail action — patient_id query param shart emas.
        if self.action in ("retrieve", "partial_update", "update", "destroy"):
            if role == "doctor":
                profile = getattr(user, "doctor_profile", None)
                if not profile:
                    return base.none()

                return base.filter(user_id__in=accepted_patient_ids(profile))
            return base.filter(user=user)

        # List — patient_id orqali filterlanadi
        patient_id = request.query_params.get("patient_id")
        if patient_id:
            target, err = resolve_target_user(request, patient_id)
            if err is not None or target is None:
                return base.none()
            qs = base.filter(user=target)
        else:
            qs = base.filter(user=user)

        type_filter = request.query_params.get("type")
        if type_filter:
            qs = qs.filter(type=type_filter)

        return qs

    @extend_schema(summary="Kasalliklar/allergiyalar ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Yangi kasallik/allergiya qo'shish")
    def create(self, request, *args, **kwargs):
        patient_id = request.data.get("patient_id")
        target, err = resolve_target_user(
            request, patient_id if patient_id else request.user.id
        )
        if err:
            return err

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(user=target, added_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Kasallik/allergiya yangilash")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Kasallik/allergiya o'chirish")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)


# --- Medical Notes ---


