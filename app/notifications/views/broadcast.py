from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _SYNC_BROADCAST_LIMIT, _broadcast_app_scope, _broadcast_targets_qs, _do_broadcast, _parse_user_ids  # underscore helper (star bermaydi)

class BroadcastSerializer(drf_serializers.Serializer):
    """Admin push/system message yuborish uchun"""

    title = drf_serializers.CharField(max_length=200)
    body = drf_serializers.CharField(max_length=1000)
    send_push = drf_serializers.BooleanField(default=True)
    send_system_message = drf_serializers.BooleanField(
        default=False,
        help_text="Har bir userning chat xonasiga system message yuborish",
    )
    role = drf_serializers.ChoiceField(
        choices=[("all", "Hamma"), ("patient", "Bemorlar"), ("doctor", "Shifokorlar")],
        default="all",
    )
    user_ids = drf_serializers.ListField(
        child=drf_serializers.IntegerField(min_value=1),
        required=False,
        help_text="Aniq user ID lar (bo'sh bo'lsa role bo'yicha hamma)",
    )

@extend_schema(tags=["Admin - Notifications"])
class AdminBroadcastViewSet(viewsets.GenericViewSet):
    """Admin — foydalanuvchilarga push notification va system message yuborish.

    Filtrlash:
        role=all — hamma
        role=patient — faqat bemorlar
        role=doctor — faqat shifokorlar
        user_ids=[1,2,3] — aniq userlar (role e'tiborsiz)
    """

    permission_classes = [IsSuperOrSimpleAdmin]
    serializer_class = BroadcastSerializer
    queryset = User.objects.none()

    @extend_schema(
        summary="Push notification yuborish (broadcast)",
        description="Filtrlangan userlarga push va/yoki system message yuboradi (async).",
    )
    @action(detail=False, methods=["post"], url_path="send")
    def send(self, request):
        serializer = BroadcastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        title = serializer.validated_data["title"]
        body = serializer.validated_data["body"]
        send_push = serializer.validated_data["send_push"]
        send_sys_msg = serializer.validated_data["send_system_message"]
        role = serializer.validated_data["role"]
        user_ids = serializer.validated_data.get("user_ids")

        target_ids = list(
            _broadcast_targets_qs(user_ids, role).values_list("id", flat=True)
        )
        app_scope = _broadcast_app_scope(role)

        # Kichik auditoriya — sinxron bajaramiz, admin push natijasini (nechta
        # yuborildi / nechta xato) DARHOL ko'radi. Aks holda 202 async'da push
        # ishlaganini bilib bo'lmaydi.
        if len(target_ids) <= _SYNC_BROADCAST_LIMIT:
            result = _do_broadcast(
                user_ids=target_ids,
                title=title,
                body=body,
                send_push=send_push,
                send_sys_msg=send_sys_msg,
                app_scope=app_scope,
                sender_id=request.user.id,
            )
            return Response(
                {
                    "queued": False,
                    "target_users": result.get("target_users", len(target_ids)),
                    "push_sent": result.get("push_sent", 0),
                    "push_failed": result.get("push_failed", 0),
                    "system_messages_sent": result.get("system_messages_sent", 0),
                    "matched_count": len(target_ids),
                    "requested_count": len(user_ids) if user_ids else None,
                },
                status=status.HTTP_200_OK,
            )

        # Katta auditoriya — async (HTTP thread bloklanmasin). Natija Celery log'da.
        run_admin_broadcast.delay(
            user_ids=target_ids,
            title=title,
            body=body,
            send_push=send_push,
            send_sys_msg=send_sys_msg,
            app_scope=app_scope,
            sender_id=request.user.id,
        )

        return Response(
            {
                "queued": True,
                "target_users": len(target_ids),
                "matched_count": len(target_ids),
                "requested_count": len(user_ids) if user_ids else None,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(summary="Broadcast uchun user soni (preview)")
    @action(detail=False, methods=["get"], url_path="preview")
    def preview(self, request):
        """Filtrlangan userllar sonini qaytaradi (yuborishdan oldin tekshirish uchun)."""
        role = request.query_params.get("role", "all")
        user_ids = _parse_user_ids(request.query_params.get("user_ids"))

        targets = _broadcast_targets_qs(user_ids, role)
        count = targets.count()
        with_push = (
            DeviceToken.objects.filter(
                user__in=targets, is_active=True, token_type=DeviceToken.TokenType.FCM
            )
            .values("user_id")
            .distinct()
            .count()
        )

        return Response(
            {
                "total_users": count,
                "with_push_token": with_push,
                "without_push_token": count - with_push,
            }
        )
