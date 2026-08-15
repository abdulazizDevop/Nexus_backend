from .common import *  # noqa: F401,F403 - header importlar + helperlar

@extend_schema(tags=["Admin - Uchrashuvlar"])
class AdminAppointmentViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin — barcha uchrashuvlarni ko'rish"""

    permission_classes = [IsAdmin]
    queryset = Appointment.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Appointment.objects.none()
        return (
            Appointment.objects.all()
            .select_related("patient", "doctor__user", "doctor__specialty")
            .order_by("-date", "-start_time")
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AppointmentDetailSerializer
        return AppointmentListSerializer

    @extend_schema(summary="Barcha uchrashuvlar ro'yxati (Admin)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Uchrashuv tafsilotlari (Admin)")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)
