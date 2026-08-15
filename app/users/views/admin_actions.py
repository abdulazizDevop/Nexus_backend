from .common import *  # noqa: F401,F403 - importlar + AVATAR_* + top-level helperlar
from .common import _protect_root, _set_role  # underscore helper (star bermaydi)


class AdminMixin:
    """Admin/super boshqaruv (role/full_info/super_admins) — UserViewSet mixin."""

    @extend_schema(
        request=ChangeRoleSerializer,
        responses=UserSerializer,
        summary="Foydalanuvchi rolini yoki admin typeni o'zgartirish (faqat Super Admin)",
        description=(
            "Super admin rolini berish yoki olib tashlash FAQAT root admin "
            "tomonidan bajariladi. Boshqa super adminlar oddiy admin/simple/seller'ni "
            "o'zgartira oladi, lekin super admin bilan ishlay olmaydi."
        ),
    )
    @action(detail=True, methods=["patch"], url_path="change-role")
    def change_role(self, request, pk=None):
        user = self.get_object()
        err = _protect_root(user, request.user)
        if err:
            return err

        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data["role"]
        new_admin_type = serializer.validated_data.get("admin_type")

        # Super admin bilan ishlash — faqat root admin
        touches_super = (
            user.is_super_admin
            or (new_role == User.Role.ADMIN and new_admin_type == User.AdminType.SUPER)
        )
        if touches_super and not request.user.is_root_admin:
            return Response(
                {
                    "detail": (
                        "Super admin yaratish yoki rolini o'zgartirish faqat "
                        "root admin qo'lida."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Rol o'rnatish + token blacklist: eski JWT'lar yangi rolni "bilmaydi"
        # (token payload'da rol cached), demote qilingan admin yana admin
        # huquqlariga ega bo'lmasligi uchun refresh token'lar blacklist qilinadi.
        _set_role(user, new_role, new_admin_type, blacklist=True)
        logger.info(
            "Role changed for user %s → %s/%s; tokens blacklisted",
            user.id, new_role, new_admin_type,
        )

        return Response(UserSerializer(user).data)

    @extend_schema(exclude=True)
    @action(detail=True, methods=["get"], url_path="full-info")
    def full_info(self, request, pk=None):
        """Admin 'to'liq user ma'lumoti' — barcha app'lardagi user datasi +
        birlashtirilgan faollik tarixi. Detail modaldagi tablar shundan yuklaydi.

        Permission: `IsSuperOrSimpleAdmin` (retrieve bilan bir xil — special
        listda emas, default fall-through)."""
        user = self.get_object()
        data = UserFullInfoSerializer(user, context=self.get_serializer_context()).data
        return Response(data)

    @extend_schema(
        summary="Super adminlar ro'yxati (faqat root admin)",
        description="Barcha super adminlarni qaytaradi. Faqat root admin chaqira oladi.",
        responses=UserAdminSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="super-admins")
    def super_admins(self, request):
        qs = User.objects.filter(
            role=User.Role.ADMIN, admin_type=User.AdminType.SUPER
        ).order_by("-date_joined")
        return Response(UserAdminSerializer(qs, many=True).data)

    @extend_schema(
        summary="Foydalanuvchini super admin qilib tayinlash (faqat root)",
        description=(
            "Berilgan user'ga role=admin, admin_type=super o'rnatadi. "
            "Agar user allaqachon super admin bo'lsa 200 bilan hech narsa o'zgarmaydi."
        ),
        responses=UserAdminSerializer,
    )
    @action(detail=True, methods=["post"], url_path="promote-super")
    def promote_super(self, request, pk=None):
        user = self.get_object()
        if user.is_super_admin:
            return Response(UserAdminSerializer(user).data)

        _set_role(user, User.Role.ADMIN, User.AdminType.SUPER)
        return Response(UserAdminSerializer(user).data)

    @extend_schema(
        summary="Super admin rolini olib tashlash (faqat root)",
        description=(
            "Super adminni oddiy admin (admin_type=simple) ga tushiradi. "
            "role=admin saqlanadi — admin panelga kira oladi. "
            "Root admin'ga nisbatan qo'llash mumkin emas."
        ),
        responses=UserAdminSerializer,
    )
    @action(detail=True, methods=["post"], url_path="demote-super")
    def demote_super(self, request, pk=None):
        user = self.get_object()
        err = _protect_root(user, request.user)
        if err:
            return err
        if not user.is_super_admin:
            return Response(
                {"detail": "Bu foydalanuvchi super admin emas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # role=admin saqlanadi (admin panelga kira oladi), faqat super → simple.
        _set_role(user, User.Role.ADMIN, User.AdminType.SIMPLE)
        return Response(UserAdminSerializer(user).data)

    @extend_schema(
        summary="Super adminni akkauntini o'chirish (faqat root)",
        description="User butunlay DB dan o'chiriladi. Root admin'ga tegmaydi.",
    )
    @action(detail=True, methods=["delete"], url_path="delete-super")
    def delete_super(self, request, pk=None):
        user = self.get_object()
        err = _protect_root(user, request.user)
        if err:
            return err
        if not user.is_super_admin:
            return Response(
                {"detail": "Bu foydalanuvchi super admin emas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
