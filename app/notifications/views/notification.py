from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _BOOL_QS  # underscore helper (star bermaydi)

@extend_schema(tags=["Notifications - Bildirishnomalar"])
class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Foydalanuvchining ichki bildirishnomalari (Notifications page).

    Endpointlar:
        GET    /api/v1/notifications/feed/                  — ro'yxat (paginated)
        GET    /api/v1/notifications/feed/{id}/             — bittasini ko'rish
        DELETE /api/v1/notifications/feed/{id}/             — bittasini o'chirish
        GET    /api/v1/notifications/feed/unread-count/     — o'qilmaganlar soni (badge)
        POST   /api/v1/notifications/feed/{id}/read/        — bittasini o'qildi qilish
        POST   /api/v1/notifications/feed/mark-read/        — ko'plarini o'qildi qilish
        POST   /api/v1/notifications/feed/mark-all-read/    — hammasini o'qildi qilish
        DELETE /api/v1/notifications/feed/clear/            — hammasini o'chirish

    Filterlar (list):
        ?is_read=true|false   — faqat o'qilgan / o'qilmagan
        ?type=treatment_reminder — turi bo'yicha (Notification.Type qiymatlari)
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    queryset = Notification.objects.none()

    def _base_qs(self):
        """User + joriy ilova scope'i (JWT) bo'yicha bazaviy queryset.

        Bemor+doctor bo'lgan user ikkala app'da login bo'lsa — har app FAQAT
        o'z scope'idagi (+ null = tizim/broadcast/legacy) notification'larni
        ko'radi. Cross-app leak'ni oldini oladi (CLAUDE.md app_scope qoidasi).
        """
        qs = Notification.objects.filter(user=self.request.user)
        scope = get_token_scope(self.request)
        if scope:
            qs = qs.filter(Q(app_scope=scope) | Q(app_scope__isnull=True))
        return qs

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()

        qs = self._base_qs()

        is_read = _BOOL_QS.get(self.request.query_params.get("is_read", ""))
        if is_read is not None:
            qs = qs.filter(is_read=is_read)

        ntype = self.request.query_params.get("type")
        if ntype:
            qs = qs.filter(type=ntype)

        return qs

    @extend_schema(
        summary="Bildirishnomalar ro'yxati",
        parameters=[
            OpenApiParameter("is_read", bool, description="O'qilgan/o'qilmaganlar"),
            OpenApiParameter(
                "type",
                str,
                description="Turi bo'yicha filter (masalan: treatment_reminder)",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Bittasini ochib ko'rish (avtomatik o'qildi qiladi)",
        description="Detail ochilganda notification avtomatik `is_read=True` ga o'tadi.",
    )
    def retrieve(self, request, *args, **kwargs):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)

    @extend_schema(summary="Bittasini o'chirish")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        summary="O'qilmaganlar soni (badge uchun)",
        responses={200: {"type": "object", "properties": {"unread": {"type": "integer"}}}},
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = self._base_qs().filter(is_read=False).count()
        return Response({"unread": count})

    @extend_schema(summary="Bittasini o'qildi qilish")
    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(self.get_serializer(notification).data)

    def _mark_read_bulk(self, filters: dict) -> int:
        return self._base_qs().filter(is_read=False, **filters).update(
            is_read=True, read_at=timezone.now()
        )

    @extend_schema(
        request=MarkReadSerializer,
        summary="Tanlanganlarni o'qildi qilish",
        responses={200: {"type": "object", "properties": {"updated": {"type": "integer"}}}},
    )
    @action(detail=False, methods=["post"], url_path="mark-read")
    def mark_read(self, request):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = self._mark_read_bulk({"id__in": serializer.validated_data["ids"]})
        return Response({"updated": updated})

    @extend_schema(
        summary="Hammasini o'qildi qilish",
        responses={200: {"type": "object", "properties": {"updated": {"type": "integer"}}}},
    )
    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        return Response({"updated": self._mark_read_bulk({})})

    @extend_schema(
        summary="Hammasini o'chirish",
        responses={200: {"type": "object", "properties": {"deleted": {"type": "integer"}}}},
    )
    @action(detail=False, methods=["delete"], url_path="clear")
    def clear(self, request):
        deleted, _ = self._base_qs().delete()
        return Response({"deleted": deleted})
