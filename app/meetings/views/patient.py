from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _initiate_call, _release_slot, _require_status, _safe_notify  # underscore helper (star bermaydi)

@extend_schema(tags=["Patient - Uchrashuvlar"])
class PatientAppointmentViewSet(viewsets.ModelViewSet):
    """Patient — uchrashuvlarni boshqarish"""

    permission_classes = [IsPatient]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Appointment.objects.none()
        return (
            Appointment.objects.filter(patient=self.request.user)
            .select_related("patient", "doctor__user", "doctor__specialty")
            .order_by("-date", "-start_time")
        )

    _serializer_by_action = {
        "create": AppointmentCreateSerializer,
        "retrieve": AppointmentDetailSerializer,
        "cancel": AppointmentCancelSerializer,
    }

    def get_serializer_class(self):
        return self._serializer_by_action.get(self.action, AppointmentListSerializer)

    @extend_schema(summary="Mening uchrashuvlarim")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Uchrashuvga yozilish (request yuborish)")
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        doctor = data["doctor"]
        date_ = data["date"]
        start = data["start_time"]
        end = data["end_time"]

        # Tarif-gate: doctor sotuvdagi tarifga ega bo'lsa-yu bemorда aktiv tarif
        # yo'q bo'lsa — jonli uchrashuv belgilash bloklanadi (chat AI gate bilan
        # bir xil mantiq). Doctor'da tarif yo'q bo'lsa — bloklamaymiz.
        from app.payments.utils import requires_tariff_purchase

        if requires_tariff_purchase(request.user, doctor):
            return Response(
                {
                    "code": "tariff_required",
                    "detail": "Bu shifokor bilan uchrashuv belgilash uchun avval tarif oling.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Atomic free→booked: slot lock + create appointment + mark booked.
        with transaction.atomic():
            slot = (
                Slot.objects.select_for_update()
                .filter(doctor=doctor, date=date_, start_time=start, end_time=end)
                .first()
            )
            if not slot:
                return Response(
                    {"detail": "Bu vaqt uchun slot mavjud emas."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if slot.status != Slot.Status.FREE:
                return Response(
                    {"detail": "Bu slot allaqachon band yoki yopilgan."},
                    status=status.HTTP_409_CONFLICT,
                )

            appointment = Appointment.objects.create(
                patient=request.user,
                doctor=doctor,
                date=date_,
                start_time=start,
                end_time=end,
                meeting_type=data.get("meeting_type", Appointment.MeetingType.OFFLINE),
                reason=data.get("reason", ""),
            )

            slot.status = Slot.Status.BOOKED
            slot.appointment = appointment
            slot.save(update_fields=["status", "appointment", "updated_at"])

        _safe_notify(
            user_id=appointment.doctor.user_id,
            type=Notification.Type.APPOINTMENT_CREATED,
            key="appointment_request",
            params={
                "name": request.user.full_name or "Bemor",
                "date": str(appointment.date),
                "time": appointment.start_time.strftime("%H:%M"),
            },
            data={"appointment_id": str(appointment.id)},
            app_scope="doctor",
        )

        return Response(
            AppointmentListSerializer(appointment).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Uchrashuv tafsilotlari")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(exclude=True)
    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(exclude=True)
    def destroy(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @extend_schema(
        request=AppointmentCancelSerializer,
        responses=AppointmentDetailSerializer,
        summary="Uchrashuvni bekor qilish",
        description="Faqat pending yoki approved holatdagi uchrashuvni bekor qilish mumkin.",
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        appointment = self.get_object()

        err = _require_status(
            appointment,
            (Appointment.Status.PENDING, Appointment.Status.APPROVED),
            "Faqat kutilayotgan yoki tasdiqlangan uchrashuvni bekor qilish mumkin.",
        )
        if err:
            return err

        serializer = AppointmentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            appointment.status = Appointment.Status.CANCELLED
            appointment.cancelled_by = Appointment.CancelledBy.PATIENT
            appointment.reject_reason = serializer.validated_data.get("reason", "")
            appointment.save(
                update_fields=["status", "cancelled_by", "reject_reason", "updated_at"]
            )
            _release_slot(appointment)

        return Response(AppointmentDetailSerializer(appointment).data)

    def _initiate_call(self, send_push: bool):
        """start-call / join-call uchun umumiy yo'l — patient → doctor."""
        appointment = self.get_object()
        doctor_user = appointment.doctor.user if appointment.doctor else None
        return _initiate_call(
            appointment,
            self.request,
            caller_scope="patient",
            callee_user_id=doctor_user.id if doctor_user else None,
            callee_scope="doctor",
            caller_label=self.request.user.full_name or "Bemor",
            send_push=send_push,
        )

    @extend_schema(
        summary="Uchrashuvni BOSHLASH (Patient → Doctor)",
        description=(
            "Bemor rejalashtirilgan uchrashuvga kiradi: LiveKit token qaytariladi "
            "VA doctor'ga `meeting_started` banner push (FCM) yuboriladi. "
            "30 soniya ichida takror chaqirilsa push qaytadan yuborilmaydi. "
            "Tugmasi: 'Uchrashuvga kirish'."
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="start-call",
        throttle_classes=[CallStartThrottle],
    )
    def start_call(self, request, pk=None):
        return self._initiate_call(send_push=True)

    @extend_schema(
        summary="Uchrashuvga QO'SHILISH (Patient)",
        description=(
            "Bemor doctor boshlagan uchrashuvga qo'shiladi: faqat LiveKit token "
            "qaytariladi, push yuborilmaydi. "
            "Tugmasi: banner notification'dagi 'Qo'shilish'."
        ),
    )
    @action(detail=True, methods=["post"], url_path="accept-call")
    def accept_call(self, request, pk=None):
        return self._initiate_call(send_push=False)

    @extend_schema(
        summary="[DEPRECATED] Video call ga qo'shilish — start-call/accept-call ishlating",
        description=(
            "Eski endpoint. Yangi mobil versiyalarda `start-call` yoki `accept-call` "
            "ishlatish kerak (push yo'nalishi to'g'ri bo'lsin uchun)."
        ),
        deprecated=True,
    )
    @action(detail=True, methods=["post"], url_path="join-call")
    def join_call(self, request, pk=None):
        return self._initiate_call(send_push=False)


# --- Doctor tomonidan ---
