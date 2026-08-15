from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar


@extend_schema(tags=["Diet AI - Admin"])
class AdminDietConversationViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin — barcha AI suhbatlarni monitoring."""

    permission_classes = [IsAdmin]
    queryset = DietConversation.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DietConversation.objects.none()
        qs = DietConversation.objects.select_related("user").prefetch_related(
            "messages"
        )
        user_id = self.request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=user_id)
        language = self.request.query_params.get("language")
        if language:
            qs = qs.filter(language=language)
        archived = self.request.query_params.get("is_archived")
        if archived is not None:
            qs = qs.filter(is_archived=archived.lower() in ("true", "1"))
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return DietConversationDetailSerializer
        return DietConversationListSerializer

    @extend_schema(summary="Barcha AI suhbatlar (admin monitoring)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Bitta suhbat tafsilotlari")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
