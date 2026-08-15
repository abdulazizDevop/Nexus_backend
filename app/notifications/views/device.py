from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _BOOL_QS  # underscore helper (star bermaydi)

@extend_schema(tags=["Notifications - Qurilmalar"])
class DeviceTokenViewSet(viewsets.ModelViewSet):
    """Foydalanuvchi qurilmalarining FCM tokenlari.

    Endpointlar:
        GET    /api/v1/notifications/devices/         — o'z qurilmalarim
        POST   /api/v1/notifications/devices/         — token registratsiya/yangilash
        DELETE /api/v1/notifications/devices/{id}/    — qurilma o'chirish (logout)
    """

    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head"]
    queryset = DeviceToken.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeviceToken.objects.none()
        return DeviceToken.objects.filter(user=self.request.user)

    @extend_schema(summary="O'z qurilmalarim ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="FCM token registratsiya / yangilash",
        description=(
            "Idempotent: agar shu token mavjud bo'lsa, last_used_at yangilanadi. "
            "Agar boshqa user'da bo'lsa, yangi user'ga o'tkaziladi."
        ),
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token_value = serializer.validated_data["token"]

        # app_scope avtomatik aniqlash: body'da explicit, yo'q bo'lsa JWT scope'dan
        app_scope = serializer.validated_data.get("app_scope") or get_token_scope(
            request
        )

        # Audit: token boshqa user'da bo'lsa ownership ko'chishini loglaymiz
        # (push-injection / DoS vektorini kuzatish uchun — token re-install'da
        # normal qayta tayinlanadi, lekin boshqa user'dan o'tishi shubhali).
        prev_owner_id = (
            DeviceToken.objects.filter(token=token_value)
            .exclude(user=request.user)
            .values_list("user_id", flat=True)
            .first()
        )
        if prev_owner_id is not None:
            logger.warning(
                "DeviceToken ownership o'zgardi: token user #%s -> user #%s",
                prev_owner_id,
                request.user.id,
            )

        device, created = DeviceToken.objects.update_or_create(
            token=token_value,
            defaults={
                "user": request.user,
                "platform": serializer.validated_data["platform"],
                "app_scope": app_scope,
                "device_id": serializer.validated_data.get("device_id", ""),
                "token_type": serializer.validated_data.get("token_type", "fcm"),
                "environment": serializer.validated_data.get(
                    "environment", "production"
                ),
                "device_name": serializer.validated_data.get("device_name", ""),
                "app_version": serializer.validated_data.get("app_version", ""),
                "is_active": True,
            },
        )

        # --- Token churn'ni cheklash (eski tokenlarni o'chirish) ---
        # 1) Bitta jismoniy qurilma (device_id) + app_scope + token_type uchun
        #    BITTA aktiv token. Yangi token kelganda o'sha qurilmaning eskilarini
        #    o'chiramiz (FCM token rotatsiyasi yangi qator yaratadi). device_id
        #    bo'sh bo'lsa skip — turli qurilmalarni adashtirmaslik uchun.
        if device.device_id:
            DeviceToken.objects.filter(
                user=request.user,
                device_id=device.device_id,
                app_scope=device.app_scope,
                token_type=device.token_type,
            ).exclude(pk=device.pk).delete()

        # 2) Reinstall'da iOS IDFV o'zgaradi → device_id ham yangi → 1-qadam
        #    ushlamaydi. Cheksiz o'smasligi uchun har (user, app_scope, token_type)
        #    bo'yicha eng so'nggi MAX_TOKENS_PER_SCOPE tokendan eskisini o'chiramiz.
        stale_ids = list(
            DeviceToken.objects.filter(
                user=request.user,
                app_scope=device.app_scope,
                token_type=device.token_type,
            )
            .order_by("-last_used_at")
            .values_list("pk", flat=True)[MAX_TOKENS_PER_SCOPE:]
        )
        if stale_ids:
            DeviceToken.objects.filter(pk__in=stale_ids).delete()

        return Response(
            DeviceTokenSerializer(device).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(summary="Qurilmani o'chirish (logout)")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)


# --- Admin Broadcast ---

class AdminDeviceTokenSerializer(drf_serializers.ModelSerializer):
    user_name = drf_serializers.CharField(source="user.full_name", read_only=True)
    user_phone = drf_serializers.CharField(source="user.phone", read_only=True)
    user_role = drf_serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = DeviceToken
        fields = [
            "id",
            "user",
            "user_name",
            "user_phone",
            "user_role",
            "token",
            "platform",
            "device_name",
            "app_version",
            "is_active",
            "created_at",
            "last_used_at",
        ]

@extend_schema(tags=["Admin - Notifications"])
class AdminDeviceTokenViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: barcha device tokenlarni ko'rish.

    Filter:
        ?user_id=5       — aniq user
        ?platform=android — platforma
        ?is_active=true   — aktiv/nofaol
        ?search=          — ism yoki telefon
    """

    serializer_class = AdminDeviceTokenSerializer
    permission_classes = [IsSuperOrSimpleAdmin]
    queryset = DeviceToken.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DeviceToken.objects.none()

        qs = DeviceToken.objects.select_related("user").order_by("-last_used_at")

        user_id = self.request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=user_id)

        platform = self.request.query_params.get("platform")
        if platform in ("ios", "android", "web"):
            qs = qs.filter(platform=platform)

        is_active = _BOOL_QS.get(self.request.query_params.get("is_active", ""))
        if is_active is not None:
            qs = qs.filter(is_active=is_active)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(user__full_name__icontains=search) | Q(user__phone__icontains=search)
            )

        return qs

    @extend_schema(summary="Barcha device tokenlar (Admin)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Token tafsilotlari")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
