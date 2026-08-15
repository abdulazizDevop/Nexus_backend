from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar + helperlar


# --- Mutaxassisliklar ---


@extend_schema(tags=["Specialty (Category)"])
class SpecialtyViewSet(viewsets.ModelViewSet):
    """Mutaxassisliklar — admin yaratadi, hammaga ko'rinadi"""

    queryset = Specialty.objects.all()
    serializer_class = SpecialtySerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsSuperOrSimpleAdmin()]

    @extend_schema(summary="Mutaxassisliklar ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


# --- Doctor profil ---


