from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar


@extend_schema(tags=["Medical - Analiz katalogi"])
class AnalysisTypeViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Analiz turlari katalogi.

    - GET  /full/      — bootstrap (auth foydalanuvchilar uchun)
    - POST /           — admin
    - PATCH /{id}/     — admin
    - DELETE /{id}/    — admin
    """

    queryset = AnalysisType.objects.prefetch_related(
        "indicators", "preparations"
    ).all()
    serializer_class = AnalysisTypeSerializer
    http_method_names = ["get", "post", "patch", "delete", "head"]

    def get_permissions(self):
        if self.action == "full":
            return [IsAuthenticated()]
        return [IsSuperOrSimpleAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnalysisType.objects.none()
        qs = AnalysisType.objects.prefetch_related("indicators", "preparations")
        # 'full' — faqat aktivlar; admin write — hammasi
        if self.action == "full":
            qs = qs.filter(is_active=True)
        return qs

    @extend_schema(
        summary="Bootstrap — barcha turlar + indicators + preparations (1 so'rov)",
        description=(
            "Analiz tayinlash formasini bitta so'rovda to'ldirish uchun: barcha "
            "aktiv analiz turlari, har biriga tegishli ko'rsatkichlar va "
            "tayyorgarlik preset'lari (universal tayyorgarliklar ham qo'shilgan) "
            "qaytariladi. Frontend dropdown, chip va checkbox'larni shu javobdan "
            "to'ldiradi — tur tanlanganda qo'shimcha so'rov shart emas."
        ),
        responses=AnalysisTypeSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="full")
    def full(self, request):


        types = list(self.get_queryset())
        type_ids = [t.id for t in types]

        preps = AnalysisPreparation.objects.filter(
            Q(type_id__in=type_ids) | Q(type__isnull=True)
        )
        by_type = defaultdict(list)
        universal = []
        for p in preps:
            if p.type_id is None:
                universal.append(p)
            else:
                by_type[p.type_id].append(p)

        # FAZA I — name/description JSONField. Admin `?include_translations=1`
        # yuborsa to'liq dict (3 til) qaytadi — frontend bir marta fetch qilib,
        # til o'zgarsa cache'dagi data'dan til'ni qaytadan tanlaydi (live switch).
        # Mobile esa oddiy `X-Language` ishlatadi — string keladi.

        params = getattr(request, "query_params", None) or getattr(request, "GET", {})
        admin_mode = params.get("include_translations") in ("1", "true", "True")

        ctx = {"request": request}

        def render_translatable(raw):
            return normalize_translations(raw) if admin_mode else pick_for(ctx, raw)

        data = []
        for t in types:
            data.append(
                {
                    "id": t.id,
                    "name": render_translatable(t.name),
                    "code": t.code,
                    "category": t.category,
                    "icon": t.icon,
                    "description": render_translatable(t.description),
                    "is_active": t.is_active,
                    "order": t.order,
                    "indicators": AnalysisIndicatorSerializer(
                        t.indicators.all(), many=True, context=ctx
                    ).data,
                    "preparations": AnalysisPreparationSerializer(
                        by_type[t.id] + universal, many=True, context=ctx
                    ).data,
                }
            )
        return Response(data)

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=["Medical - Analiz katalogi"])
class AnalysisIndicatorViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Analiz ko'rsatkichlari katalogi — admin CRUD."""

    queryset = AnalysisIndicator.objects.select_related("type").all()
    serializer_class = AnalysisIndicatorSerializer
    permission_classes = [IsSuperOrSimpleAdmin]
    http_method_names = ["post", "patch", "delete", "head"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnalysisIndicator.objects.none()
        return AnalysisIndicator.objects.select_related("type")

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=["Medical - Analiz katalogi"])
class AnalysisPreparationViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Tayyorgarlik preset'lari katalogi — admin CRUD."""

    queryset = AnalysisPreparation.objects.select_related("type").all()
    serializer_class = AnalysisPreparationSerializer
    permission_classes = [IsSuperOrSimpleAdmin]
    http_method_names = ["post", "patch", "delete", "head"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnalysisPreparation.objects.none()
        return AnalysisPreparation.objects.select_related("type")

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)




