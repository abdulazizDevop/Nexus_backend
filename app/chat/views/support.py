from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + pagination
from .common import _BOOL_QS,_broadcast_ws,_is_admin_role,_is_awaiting_reply


# --- Support Chat ---


@extend_schema(tags=["Support Chat"])
class SupportChatViewSet(viewsets.GenericViewSet):
    """Support chat — user murojaat qiladi, barcha adminlar javob beradi.

    User uchun:
        POST /support/           — support chat ochish (yoki mavjudni qaytarish)
        GET  /support/me/        — o'z support chatim
        GET  /support/me/messages/ — xabarlar

    Admin uchun:
        GET  /support/           — barcha support chatlar
        GET  /support/{id}/      — bitta chat
        GET  /support/{id}/messages/ — xabarlar
        POST /support/{id}/reply/    — javob yozish
        POST /support/{id}/close/    — chatni yopish
    """

    permission_classes = [IsAuthenticated]
    queryset = ChatRoom.objects.none()

    def get_serializer_class(self):
        if self.action == "messages":
            return MessageSerializer
        return ChatRoomDetailSerializer

    @extend_schema(summary="Support chatlar ro'yxati (admin) yoki chat ochish (user)")
    def list(self, request):
        if _is_admin_role(request.user):
            # Admin: barcha support chatlar
            _last_real = (
                Message.objects.filter(room=OuterRef("pk"), is_deleted=False)
                .exclude(message_type=Message.MessageType.SYSTEM)
                .order_by("-created_at")
            )
            qs = (
                ChatRoom.objects.filter(room_type=ChatRoom.RoomType.SUPPORT)
                .prefetch_related("participants")
                .annotate(
                    unread_count=unread_count_annotation(exclude_admin=True),
                    last_message_at=Max("messages__created_at"),
                    last_scope=Subquery(_last_real.values("sender_scope")[:1]),
                    last_role=Subquery(_last_real.values("sender__role")[:1]),
                )
                .order_by("-updated_at")
            )

            is_active = _BOOL_QS.get(request.query_params.get("is_active", ""))
            if is_active is not None:
                qs = qs.filter(is_active=is_active)

            data = []
            for room in qs:
                user = room.participants.exclude(role=User.Role.ADMIN).first()
                last_msg = (
                    room.messages.filter(is_deleted=False)
                    .order_by("-created_at")
                    .first()
                )
                data.append(
                    {
                        "id": room.id,
                        "room_type": room.room_type,
                        "user": (
                            {
                                "id": user.id,
                                "full_name": user.full_name,
                                "phone": user.phone,
                                "role": user.role,
                            }
                            if user else None
                        ),
                        "unread_count": getattr(room, "unread_count", 0),
                        "awaiting_reply": _is_awaiting_reply(
                            getattr(room, "last_scope", None),
                            getattr(room, "last_role", None),
                        ),
                        "last_message": (
                            {
                                "content": (
                                    last_msg.content[:100]
                                    if last_msg.content else None
                                ),
                                "sender_name": last_msg.sender.full_name,
                                "sender_role": last_msg.sender.role,
                                "created_at": last_msg.created_at.isoformat(),
                            }
                            if last_msg else None
                        ),
                        "is_active": room.is_active,
                        "created_at": room.created_at.isoformat(),
                        "updated_at": room.updated_at.isoformat(),
                    }
                )

            # Javob kutayotgan (bemor oxirgi yozgan) suhbatlar birinchi, so'ng so'nggi faol.
            data.sort(key=lambda d: (d["awaiting_reply"], d["updated_at"]), reverse=True)
            return Response(data)

        # User: o'z support chati yo'q bo'lsa bo'sh list
        room = (
            ChatRoom.objects.filter(
                room_type=ChatRoom.RoomType.SUPPORT,
                participants=request.user,
            )
            .prefetch_related("participants")
            .first()
        )
        if not room:
            return Response([])

        return Response(
            [ChatRoomDetailSerializer(room, context={"request": request}).data]
        )

    @extend_schema(
        summary="Support chat ochish",
        description="User o'zi uchun ochadi. Admin user_id yuborib boshqa user uchun ochadi.",
    )
    def create(self, request):
        # Admin: user_id orqali boshqa user uchun chat ochadi
        user_id = request.data.get("user_id")
        if _is_admin_role(request.user) and user_id:
            try:
                target_user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({"detail": "Foydalanuvchi topilmadi."}, status=404)
        else:
            target_user = request.user

        existing = ChatRoom.objects.filter(
            room_type=ChatRoom.RoomType.SUPPORT,
            participants=target_user,
        ).first()

        if existing:
            return Response(
                ChatRoomDetailSerializer(existing, context={"request": request}).data,
                status=status.HTTP_200_OK,
            )

        room = ChatRoom.objects.create(room_type=ChatRoom.RoomType.SUPPORT)
        room.participants.add(target_user)

        Message.create_system(
            room,
            "Qo'llab-quvvatlash chatiga xush kelibsiz.",
            sender=request.user,
            scope=get_token_scope(request),
        )

        return Response(
            ChatRoomDetailSerializer(room, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def _support_room(self, request, pk, *, admin_can_access_any=True):
        """Support xona — admin barcha xonalarga, oddiy user faqat o'zining xonasiga."""
        if _is_admin_role(request.user) and admin_can_access_any:
            return ChatRoom.objects.filter(
                id=pk, room_type=ChatRoom.RoomType.SUPPORT
            ).first()
        return ChatRoom.objects.filter(
            id=pk,
            room_type=ChatRoom.RoomType.SUPPORT,
            participants=request.user,
        ).first()

    @extend_schema(summary="Support chat tafsilotlari")
    def retrieve(self, request, pk=None):
        room = self._support_room(request, pk)
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        room = ChatRoom.objects.filter(id=room.id).prefetch_related("participants").first()
        return Response(
            ChatRoomDetailSerializer(room, context={"request": request}).data
        )

    @extend_schema(summary="O'z support chatim (user)")
    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        room = (
            ChatRoom.objects.filter(
                room_type=ChatRoom.RoomType.SUPPORT,
                participants=request.user,
            )
            .prefetch_related("participants")
            .first()
        )

        if not room:
            return Response({"detail": "Support chat ochilmagan."}, status=404)

        return Response(
            ChatRoomDetailSerializer(room, context={"request": request}).data
        )

    @extend_schema(summary="Support chat xabarlari")
    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request, pk=None):
        room = self._support_room(request, pk)
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        qs = Message.objects.filter(room=room, is_deleted=False).select_related(
            "sender"
        )
        paginator = MessagePagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = MessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Admin javob yozish (text, file, reply)",
        description="content = matn. reply_to = javob beriladigan xabar ID. "
                    "file_key/file_name/file_size/file_type = fayl yuborishda.",
    )
    @action(detail=True, methods=["post"], url_path="reply")
    def reply(self, request, pk=None):
        if not _is_admin_role(request.user):
            return Response({"detail": "Faqat admin javob yoza oladi."}, status=403)

        room = ChatRoom.objects.filter(
            id=pk, room_type=ChatRoom.RoomType.SUPPORT
        ).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        content = request.data.get("content", "").strip()
        reply_to_id = request.data.get("reply_to")
        # XAVFSIZLIK/BUG: reply_to faqat ayni shu xonadagi mavjud xabarga ishora
        # qilishi shart — yaroqsiz/boshqa xona ID IntegrityError yoki cross-room
        # reply keltirib chiqaradi.
        if reply_to_id and not Message.objects.filter(
            id=reply_to_id, room=room, is_deleted=False
        ).exists():
            reply_to_id = None
        file_key = request.data.get("file_key", "")
        file_name = request.data.get("file_name", "")
        file_size = request.data.get("file_size")
        file_type = request.data.get("file_type", "")

        if file_key:
            # XAVFSIZLIK: file_key shu xonaga tegishli + S3 HeadObject bilan
            # real MIME/size tekshiruvi (IDOR + spoofing/malware oldini olish).
            # Verify mantiqi WS consumer bilan umumiy (app/chat/utils.py).
            if not file_key.startswith(f"chat/{room.id}/"):
                return Response({"detail": "Noto'g'ri file_key"}, status=400)
            verified = verify_chat_upload(file_key)
            if not verified["ok"]:
                return Response({"detail": verified["error"]}, status=400)
            # Client'dan emas, real obyektdan
            file_type = verified["mime"]
            file_size = verified["size"]
            msg_type = verified["message_type"]
        else:
            msg_type = Message.MessageType.TEXT
            if not content:
                return Response({"detail": "Xabar matni bo'sh."}, status=400)

        # Ovozli xabar: kelishilgan skip-logic (webm/opus/ogg → pending+transcode).
        audio_status = initial_audio_status(msg_type, file_type, file_name)

        msg = Message.objects.create(
            room=room,
            sender=request.user,
            sender_scope=get_token_scope(request),
            message_type=msg_type,
            content=content,
            file_key=file_key,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            audio_status=audio_status,
            reply_to_id=reply_to_id,
        )
        room.save(update_fields=["updated_at"])

        # REST view sinxron — `.delay()` to'g'ridan-to'g'ri xavfsiz.
        enqueue_transcode_if_pending(msg.id, audio_status)

        _broadcast_ws(
            room.id,
            {
                "type": "chat.new_message",
                "message": {
                    "id": msg.id,
                    "sender": msg.sender_id,
                    "sender_name": msg.sender.full_name,
                    "sender_role": msg.sender.role,
                    "sender_admin_type": msg.sender.admin_type,
                    "message_type": msg.message_type,
                    "content": msg.content,
                    "file_key": msg.file_key,
                    "file_name": msg.file_name,
                    "file_size": msg.file_size,
                    "file_type": msg.file_type,
                    "audio_status": msg.audio_status,
                    "reply_to": msg.reply_to_id,
                    "created_at": msg.created_at.isoformat(),
                },
            },
        )

        # Notification + push userga — user qaysi app'dan yozayotgani role/active_role'iga qarab
        user = room.participants.exclude(role=User.Role.ADMIN).first()
        if user:
            user_scope = (
                getattr(user, "active_role", None) or getattr(user, "role", None)
            )
            try:
                notify_by_key_user.delay(
                    user_id=user.id,
                    type=Notification.Type.SUPPORT_MESSAGE,
                    key="support_reply",
                    params={
                        "sender_name": request.user.full_name or "Support",
                        "snippet": content[:100],
                    },
                    data={"room_id": str(room.id)},
                    app_scope=user_scope,
                )
            except Exception:
                pass

        return Response(MessageSerializer(msg).data, status=201)

    @extend_schema(summary="Fayl yuklash uchun presigned URL (support chat)")
    @action(detail=True, methods=["post"], url_path="upload-url")
    def upload_url(self, request, pk=None):
        if not _is_admin_role(request.user):
            return Response({"detail": "Faqat admin fayl yuklashi mumkin."}, status=403)

        room = ChatRoom.objects.filter(
            id=pk, room_type=ChatRoom.RoomType.SUPPORT
        ).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        file_name = request.data.get("file_name", "file")
        file_type = request.data.get("file_type", "application/octet-stream")

        if file_type == "application/octet-stream" and file_name:
            guessed, _ = mimetypes.guess_type(file_name)
            if guessed:
                file_type = guessed

        file_key = generate_file_key(room.id, file_name)
        url = generate_upload_url(file_key, file_type)

        return Response(
            {
                "upload_url": url,
                "file_key": file_key,
                "content_type": file_type,
                "expires_in": 900,
            }
        )

    @extend_schema(summary="Support chatni yopish")
    @action(detail=True, methods=["post"], url_path="close")
    def close(self, request, pk=None):
        if not _is_admin_role(request.user):
            return Response({"detail": "Faqat admin yopa oladi."}, status=403)

        room = ChatRoom.objects.filter(
            id=pk, room_type=ChatRoom.RoomType.SUPPORT
        ).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        room.is_active = False
        room.save(update_fields=["is_active", "updated_at"])

        Message.create_system(
            room,
            f"Chat {request.user.full_name} tomonidan yopildi.",
            sender=request.user,
            scope=get_token_scope(request),
        )

        return Response({"detail": "Support chat yopildi"})


