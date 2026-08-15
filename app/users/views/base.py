from .common import *  # noqa: F401,F403 - importlar + AVATAR_* + top-level helperlar
from .common import _protect_root  # underscore helper (star bermaydi)
from .self_actions import SelfMixin
from .admin_actions import AdminMixin
from .connections import ConnectionMixin


@extend_schema(tags=["Users"])
class UserViewSet(SelfMixin, AdminMixin, ConnectionMixin, viewsets.ModelViewSet):
    """Foydalanuvchilar CRUD"""

    queryset = User.objects.none()
    parser_classes = [MultiPartParser, JSONParser]

    def get_serializer_class(self):
        if getattr(self, "swagger_fake_view", False):
            return UserSerializer
        if self.action == "me":
            if self.request.method == "PATCH":
                return UserUpdateSerializer
            return UserSerializer
        # JWT scope'dan rol — admin doctor sifatida switch qilsa, asosiy
        # role=admin lekin active scope=doctor → user list admin serializer'ni
        # qaytarmasligi kerak.
        if get_request_role(self.request) == User.Role.ADMIN:
            if self.action == "retrieve":
                return UserAdminDetailSerializer
            return UserAdminSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action in (
            "me",
            "delete_my_account",
            "link_doctor",
            "my_doctors",
            "add_doctor",
            "disconnect_doctor",
            "avatar_upload_url",
            "switch_role",
            "pending_connections",
            "accept_connection",
            "decline_connection",
        ):
            return [IsAuthenticated()]
        if self.action == "change_role":
            return [IsSuperAdmin()]
        if self.action in (
            "super_admins",
            "promote_super",
            "demote_super",
            "delete_super",
        ):
            return [IsRootAdmin()]
        return [IsSuperOrSimpleAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        qs = User.objects.select_related("settings").all()
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(full_name__icontains=search) | Q(phone__icontains=search))
        return qs

    # Admin CRUD — Swagger dan yashirilgan, kerak bo'lganda ochiladi

    @extend_schema(exclude=True)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        err = _protect_root(self.get_object(), request.user)
        if err:
            return err
        return super().update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        err = _protect_root(self.get_object(), request.user)
        if err:
            return err
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        err = _protect_root(self.get_object(), request.user)
        if err:
            return err
        return super().destroy(request, *args, **kwargs)
