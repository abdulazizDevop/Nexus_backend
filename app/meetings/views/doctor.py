from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _initiate_call, _release_slot, _require_status, _safe_notify  # underscore helper (star bermaydi)

@extend_schema(tags=["Doctor - Uchrashuvlar"])
class DoctorAppointmentViewSet(viewsets.ModelViewSet):
    """Doctor — uchrashuvlarni boshqarish (tasdiqlash/rad etish)"""

    permission_classes = [IsVerifiedDoctor]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Appointment.objects.none()
        return (
            Appointment.objects.filter(doctor__user=self.request.user)
            .select_related("patient", "doctor__user", "doctor__specialty")
            .order_by("-date", "-start_time")
        )

    _serializer_by_action = {
        "retrieve": AppointmentDetailSerializer,
        "approve": AppointmentApproveSerializer,
        "reject": AppointmentRejectSerializer,
        "complete": AppointmentApproveSerializer,
    }

    def get_serializer_class(self):
        return self._serializer_by_action.get(self.action, AppointmentListSerializer)

    @extend_schema(summary="Doctor uchrashuvlari ro'yxati")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Uchrashuv tafsilotlari")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(exclude=True)
    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

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
        request=AppointmentApproveSerializer,
        responses=AppointmentDetailSerializer,
        summary="Uchrashuvni tasdiqlash",
        description="Faqat pending holatdagi uchrashuvni tasdiqlash mumkin.",
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        appointment = self.get_object()

        err = _require_status(
            appointment,
            Appointment.Status.PENDING,
            "Faqat kutilayotgan uchrashuvni tasdiqlash mumkin.",
        )
        if err:
            return err

        serializer = AppointmentApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        appointment.status = Appointment.Status.APPROVED
        appointment.notes = serializer.validated_data.get("notes", "")

        if (
            appointment.meeting_type == Appointment.MeetingType.ONLINE
            and not appointment.room_name
        ):
            appointment.room_name = generate_room_name()
            # Redis/Celery o'chgan bo'lsa sinxron fallback
            try:
                create_livekit_room.delay(appointment.room_name, appointment.id)
            except Exception:
                create_room(appointment.room_name)

        appointment.save(update_fields=["status", "notes", "room_name", "updated_at"])

        _safe_notify(
            user_id=appointment.patient_id,
            type=Notification.Type.APPOINTMENT_APPROVED,
            key="appointment_approved",
            params={
                "doctor_name": request.user.full_name or "Shifokoringiz",
                "date": str(appointment.date),
                "time": appointment.start_time.strftime("%H:%M"),
            },
            data={"appointment_id": str(appointment.id)},
            app_scope="patient",
        )

        return Response(AppointmentDetailSerializer(appointment).data)

    @extend_schema(
        request=AppointmentRejectSerializer,
        responses=AppointmentDetailSerializer,
        summary="Uchrashuvni rad etish",
        description="Faqat pending holatdagi uchrashuvni rad etish mumkin. Sabab kiritish majburiy.",
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        appointment = self.get_object()

        err = _require_status(
            appointment,
            Appointment.Status.PENDING,
            "Faqat kutilayotgan uchrashuvni rad etish mumkin.",
        )
        if err:
            return err

        serializer = AppointmentRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            appointment.status = Appointment.Status.REJECTED
            appointment.cancelled_by = Appointment.CancelledBy.DOCTOR
            appointment.reject_reason = serializer.validated_data["reject_reason"]
            appointment.save(
                update_fields=["status", "cancelled_by", "reject_reason", "updated_at"]
            )
            _release_slot(appointment)

        _safe_notify(
            user_id=appointment.patient_id,
            type=Notification.Type.APPOINTMENT_REJECTED,
            key="appointment_rejected",
            params={
                "doctor_name": request.user.full_name or "Shifokor",
                "reason": appointment.reject_reason or "sabab ko'rsatilmadi",
            },
            data={"appointment_id": str(appointment.id)},
            app_scope="patient",
        )

        return Response(AppointmentDetailSerializer(appointment).data)

    @extend_schema(
        request=AppointmentApproveSerializer,
        responses=AppointmentDetailSerializer,
        summary="Uchrashuvni yakunlash",
        description="Approved holatdagi uchrashuvni yakunlash (uchrashuv o'tdi).",
    )
    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        appointment = self.get_object()

        err = _require_status(
            appointment,
            Appointment.Status.APPROVED,
            "Faqat tasdiqlangan uchrashuvni yakunlash mumkin.",
        )
        if err:
            return err

        serializer = AppointmentApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        appointment.status = Appointment.Status.COMPLETED
        if serializer.validated_data.get("notes"):
            appointment.notes = serializer.validated_data["notes"]
        appointment.save(update_fields=["status", "notes", "updated_at"])

        # Review-reminder bitta manbadan — task ichida idempotency guard'lar bor
        # (status==COMPLETED + Review mavjudligi tekshiruvi), auto-complete bilan
        # bir xil xulq va dublikat notification oldini oladi.
        send_review_request_notification.delay(appointment.id)

        return Response(AppointmentDetailSerializer(appointment).data)

    def _initiate_call(self, send_push: bool):
        """start-call / join-call uchun umumiy yo'l — doctor → patient."""
        appointment = self.get_object()
        doctor_label = (
            f"Dr. {self.request.user.full_name}"
            if self.request.user.full_name
            else "Shifokor"
        )
        return _initiate_call(
            appointment,
            self.request,
            caller_scope="doctor",
            callee_user_id=appointment.patient_id,
            callee_scope="patient",
            caller_label=doctor_label,
            send_push=send_push,
        )

    @extend_schema(
        summary="Uchrashuvni BOSHLASH (Doctor → Patient)",
        description=(
            "Doctor rejalashtirilgan uchrashuvga kiradi: LiveKit token qaytariladi "
            "VA bemorga `meeting_started` banner push (FCM) yuboriladi. "
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
        summary="Uchrashuvga QO'SHILISH (Doctor)",
        description=(
            "Doctor bemor boshlagan uchrashuvga qo'shiladi: faqat LiveKit token "
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


# --- Admin tomonidan ---
