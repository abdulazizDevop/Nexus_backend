from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + pagination


@extend_schema(tags=["Chat - Online Status"])
class OnlineStatusView(viewsets.ViewSet):
    """User online/offline holati"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Userlar online holati",
        parameters=[
            OpenApiParameter(
                name="user_ids",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Vergul bilan ajratilgan user ID lar (masalan: 1,2,3)",
            )
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def list(self, request):
        user_ids = request.query_params.get("user_ids", "")
        if not user_ids:
            return Response({})

        requested = {uid.strip() for uid in user_ids.split(",") if uid.strip().isdigit()}
        if not requested:
            return Response({})

        # XAVFSIZLIK: faqat so'rovchi bilan chat xonasini bo'lishadigan user'larning
        # online holatini qaytaramiz. Aks holda istalgan authenticated user ixtiyoriy
        # ID'lar presence'ini (va id enumeratsiyasini) oshkor qila olardi.
        related_ids = set(
            User.objects.filter(
                id__in=requested,
                chat_rooms__participants=request.user,
            )
            .values_list("id", flat=True)
            .distinct()
        )

        # ?detail=1 → {uid: {online, last_seen}} (presence v2 — web + mobil Faza 2).
        # Default (param yo'q) → {uid: bool} (eski shakl, hozirgi mobil sinmaydi).
        detail = request.query_params.get("detail")
        result = {}
        for uid in requested:
            if int(uid) not in related_ids:
                continue
            if detail:
                result[uid] = {"online": is_online(uid), "last_seen": get_last_seen(uid)}
            else:
                result[uid] = is_online(uid)

        return Response(result)


# --- Admin ---


