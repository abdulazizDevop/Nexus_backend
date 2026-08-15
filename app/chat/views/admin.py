from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + pagination
from .common import _BOOL_QS,_is_awaiting_reply,_support_last_sender_qs


@extend_schema(tags=["Admin - Chat"])
class AdminChatRoomViewSet(
    viewsets.GenericViewSet,
    viewsets.mixins.ListModelMixin,
    viewsets.mixins.RetrieveModelMixin,
):
    """Admin — chatlarni monitoring qilish"""

    permission_classes = [IsAdmin]
    queryset = ChatRoom.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChatRoom.objects.none()

        latest_msg = Message.objects.filter(
            is_deleted=False,
            id=Subquery(
                Message.objects.filter(room_id=OuterRef("room_id"), is_deleted=False)
                .order_by("-created_at")
                .values("id")[:1]
            ),
        )
        # Oxirgi (system bo'lmagan) xabar yuborilgan scope/role — 'javob kutmoqda'
        # (bemor oxirgi yozgan) uchun. is_read'ga bog'liq emas; ko'p rolli userni
        # to'g'ri hisoblaydi (User.role emas — sender_scope).
        _last_real = (
            Message.objects.filter(room=OuterRef("pk"), is_deleted=False)
            .exclude(message_type=Message.MessageType.SYSTEM)
            .order_by("-created_at")
        )
        qs = (
            ChatRoom.objects.all()
            .prefetch_related(
                "participants",
                Prefetch("messages", queryset=latest_msg, to_attr="latest_messages"),
            )
            .annotate(
                message_count=Count("messages", filter=Q(messages__is_deleted=False)),
                unread_count=unread_count_annotation(),
                last_message_at=Max("messages__created_at"),
                _last_by=Coalesce(
                    Subquery(_last_real.values("sender_scope")[:1]),
                    Subquery(_last_real.values("sender__role")[:1]),
                    output_field=CharField(),
                ),
            )
            .annotate(
                awaiting_reply=Case(
                    When(
                        Q(room_type=ChatRoom.RoomType.SUPPORT)
                        & Q(_last_by__isnull=False)
                        & ~Q(_last_by=User.Role.ADMIN),
                        then=Value(True),
                    ),
                    default=Value(False),
                    output_field=BooleanField(),
                ),
            )
            # Javob kutayotgan support suhbatlari birinchi, keyin so'nggi faol.
            .order_by("-awaiting_reply", "-updated_at")
        )

        room_type = self.request.query_params.get("room_type")
        if room_type in ("consultation", "support"):
            qs = qs.filter(room_type=room_type)

        is_active = _BOOL_QS.get(self.request.query_params.get("is_active", ""))
        if is_active is not None:
            qs = qs.filter(is_active=is_active)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(participants__full_name__icontains=search).distinct()

        date_from = self.request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AdminChatRoomDetailSerializer
        if self.action == "messages":
            return MessageSerializer
        return AdminChatRoomListSerializer

    @extend_schema(summary="Barcha chatlar (Admin)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Chat tafsilotlari (Admin)")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Chat xabarlari (Admin)")
    @action(
        detail=True,
        methods=["get"],
        url_path="messages",
        pagination_class=MessagePagination,
    )
    def messages(self, request, pk=None):
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        qs = Message.objects.filter(room=room, is_deleted=False).select_related(
            "sender"
        )

        message_type = request.query_params.get("message_type")
        if message_type in ("text", "image", "video", "audio", "file", "system"):
            qs = qs.filter(message_type=message_type)

        paginator = MessagePagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = MessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(summary="Chat statistikasi (Admin)")
    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_rooms = ChatRoom.objects.count()
        active_rooms = ChatRoom.objects.filter(is_active=True).count()
        total_messages = Message.objects.filter(is_deleted=False).count()
        messages_today = Message.objects.filter(
            is_deleted=False, created_at__gte=today_start
        ).count()
        unread_messages = Message.objects.filter(
            is_deleted=False, is_read=False
        ).count()

        active_today = (
            ChatRoom.objects.filter(
                messages__created_at__gte=today_start,
                messages__is_deleted=False,
            )
            .distinct()
            .count()
        )

        # Online userlar soni
        user_ids = User.objects.filter(
            role__in=[User.Role.DOCTOR, User.Role.PATIENT]
        ).values_list("id", flat=True)
        online_count = sum(1 for uid in user_ids if is_online(uid))

        # Support: javob KUTAYOTGAN suhbatlar — oxirgi (system bo'lmagan) xabar
        # ADMIN scope'idan EMAS (bemor yozgan, admin javob bermagan). is_read'ga
        # bog'liq emas; ko'p rolli userni to'g'ri hisoblaydi (sender_scope).
        support_unanswered_rooms = sum(
            1
            for r in _support_last_sender_qs()
            if _is_awaiting_reply(r.last_scope, r.last_role)
        )

        return Response(
            {
                "total_rooms": total_rooms,
                "active_rooms": active_rooms,
                "inactive_rooms": total_rooms - active_rooms,
                "active_today": active_today,
                "total_messages": total_messages,
                "messages_today": messages_today,
                "unread_messages": unread_messages,
                "online_users": online_count,
                "support_unanswered_rooms": support_unanswered_rooms,
            }
        )

    def _toggle_active(self, request, pk, *, target_active: bool, content_template: str):
        room = ChatRoom.objects.filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)
        if room.is_active == target_active:
            label = "faol" if target_active else "yopilgan"
            return Response({"detail": f"Chat allaqachon {label}"}, status=400)

        room.is_active = target_active
        room.save(update_fields=["is_active", "updated_at"])

        Message.create_system(
            room,
            content_template,
            sender=request.user,
            scope=get_token_scope(request),
        )
        return room

    @extend_schema(summary="Chatni yopish (deactivate)")
    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        result = self._toggle_active(
            request, pk,
            target_active=False,
            content_template="Chat admin tomonidan yopildi.",
        )
        if isinstance(result, Response):
            return result
        return Response({"detail": "Chat yopildi", "is_active": False})

    @extend_schema(summary="Chatni qayta ochish (activate)")
    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        result = self._toggle_active(
            request, pk,
            target_active=True,
            content_template="Chat admin tomonidan qayta ochildi.",
        )
        if isinstance(result, Response):
            return result
        return Response({"detail": "Chat qayta ochildi", "is_active": True})

    @extend_schema(summary="Chat qo'ng'iroqlar tarixi (Admin)")
    @action(detail=True, methods=["get"], url_path="call-history")
    def call_history(self, request, pk=None):
        room = ChatRoom.objects.filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        sessions = CallSession.objects.filter(room=room).select_related(
            "caller", "callee"
        )[:50]
        return Response(CallSessionSerializer(sessions, many=True).data)
