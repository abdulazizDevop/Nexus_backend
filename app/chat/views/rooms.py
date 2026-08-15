from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar + pagination
from .common import _broadcast_ws,_other_participant_scope,_send_call_cancel_push


@extend_schema(tags=["Chat"])
class ChatRoomViewSet(viewsets.GenericViewSet):
    """Doctor/Patient — chat xonalarini boshqarish"""

    permission_classes = [IsDoctorOrPatient]
    queryset = ChatRoom.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChatRoom.objects.none()
        # Har room uchun OXIRGI xabarni bitta prefetch'da olamiz (N+1 oldini
        # olish — _latest_message keshdan o'qiydi). Subquery har room uchun bitta
        # eng yangi xabar id'sini topadi (portable: PostgreSQL + SQLite).
        latest_msg = Message.objects.filter(
            is_deleted=False,
            id=Subquery(
                Message.objects.filter(room_id=OuterRef("room_id"), is_deleted=False)
                .order_by("-created_at")
                .values("id")[:1]
            ),
        )
        qs = (
            ChatRoom.objects.filter(participants=self.request.user, is_active=True)
            .prefetch_related(
                "participants",
                Prefetch("messages", queryset=latest_msg, to_attr="latest_messages"),
            )
            .annotate(
                unread_count=unread_count_annotation(
                    exclude_sender=self.request.user,
                    doctor_cutoff_user=self.request.user,
                )
            )
            .order_by("-updated_at")
        )

        # Marketplace privacy: agar user DOCTOR profiliga ega bo'lsa, o'zining
        # doctor-profilidagi consultation room'lardan ACCEPTED-ulanmaganlarini
        # (marketplace AI, xariddan oldingi) yashiramiz. Bemor-tomondagi room'lar
        # va support room'lar tegilmaydi (scope'dan mustaqil, room egaligi bo'yicha).
        doctor_profile = DoctorProfile.objects.filter(user=self.request.user).first()
        if doctor_profile:
            connected_patient_ids = DoctorPatient.objects.filter(
                doctor=doctor_profile, status=DoctorPatient.Status.ACCEPTED
            ).values("patient_id")
            hidden_room_ids = (
                ChatRoom.objects.filter(
                    room_type=ChatRoom.RoomType.CONSULTATION, doctor=doctor_profile
                )
                .exclude(patient__user_id__in=Subquery(connected_patient_ids))
                .values("id")
            )
            qs = qs.exclude(id__in=Subquery(hidden_room_ids))

        return qs

    _serializer_by_action = {
        "create": ChatRoomCreateSerializer,
        "retrieve": ChatRoomDetailSerializer,
        "messages": MessageSerializer,
        "upload_url": UploadURLSerializer,
    }

    def get_serializer_class(self):
        return self._serializer_by_action.get(self.action, ChatRoomListSerializer)

    @extend_schema(summary="Chatlarim ro'yxati")
    def list(self, request):
        qs = self.get_queryset()
        serializer = ChatRoomListSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @extend_schema(summary="Chat detail")
    def retrieve(self, request, pk=None):
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)
        return Response(
            ChatRoomDetailSerializer(room, context={"request": request}).data
        )

    @extend_schema(
        summary="Chat yaratish yoki mavjudni olish",
        description=(
            "Patient → doctor_id yuboradi.\n"
            "Doctor → patient_id yuboradi.\n"
            "Mavjud room bo'lsa qaytaradi (idempotent)."
        ),
    )
    def create(self, request):
        """Chat xona ochish.

        JWT scope va patient_id/doctor_id'dan kelib chiqib, AYNAN qaysi Patient
        va Doctor o'rtasidagi xona ekanini aniqlaymiz. Bir user bir vaqtda ham
        bemor, ham doctor bo'lishi mumkin — har rol-context uchun ALOHIDA xona.
        """
        serializer = ChatRoomCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doctor_id = serializer.validated_data.get("doctor_id")
        patient_id = serializer.validated_data.get("patient_id")
        scope = get_request_role(request)

        # Rol vs nishon: o'zining boshqa rolidagi profiliga chat ochish mumkin
        # (Patient va DoctorProfile alohida identitilar), lekin patient↔patient
        # yoki doctor↔doctor consultation bo'lmaydi.
        if scope == "patient" and patient_id:
            return Response(
                {"detail": "Patient sifatida boshqa patient bilan chat ochib bo'lmaydi."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if scope == "doctor" and doctor_id:
            return Response(
                {"detail": "Doctor sifatida boshqa doctor bilan chat ochib bo'lmaydi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Aniq Patient + Doctor profil topish
        patient_profile = None
        doctor_profile = None

        if scope == "doctor" and patient_id:
            doctor_profile = DoctorProfile.objects.filter(user=request.user).first()
            if not doctor_profile:
                return Response(
                    {"detail": "Doctor profilingiz mavjud emas."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                patient_user = User.objects.get(id=patient_id)
            except User.DoesNotExist:
                return Response({"detail": "Bemor topilmadi"}, status=404)
            # XAVFSIZLIK: faqat ACCEPTED bog'lanish bo'lsa chat/qo'ng'iroq mumkin.
            # (medical/diet_ai/health_packages bilan bir xil invariant — aks holda
            # doctor istalgan User'ni chaqirib spam/harassment qila oladi.)
            if not DoctorPatient.objects.filter(
                doctor=doctor_profile,
                patient=patient_user,
                status=DoctorPatient.Status.ACCEPTED,
            ).exists():
                return Response(
                    {"detail": "Bu bemor bilan tasdiqlangan bog'lanish mavjud emas."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            patient_profile = Patient.objects.filter(user=patient_user).first()
            if not patient_profile:
                patient_profile = Patient.objects.create(user=patient_user)
        elif doctor_id:
            try:
                # Faqat tasdiqlangan (is_verified) doctor bilan chat ochish mumkin —
                # meetings booking bilan bir xil invariant (CLAUDE.md: doctor faqat
                # is_verified=True bo'lgach to'liq ishlaydi).
                doctor_profile = DoctorProfile.objects.get(
                    id=doctor_id, user__is_active=True, is_verified=True
                )
            except DoctorProfile.DoesNotExist:
                return Response({"detail": "Doctor topilmadi"}, status=404)
            patient_profile = Patient.objects.filter(user=request.user).first()
            if not patient_profile:
                patient_profile = Patient.objects.create(user=request.user)
        else:
            return Response(
                {"detail": "doctor_id yoki patient_id majburiy."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Aniq Patient + Doctor bo'yicha unique xona. User A patient sifatida
        # B doctor bilan chat'i ALOHIDA, User A doctor sifatida B patient
        # bilan chat'i ALOHIDA.
        room, created = ChatRoom.get_or_create_consultation(
            patient_profile, doctor_profile
        )

        if created:
            Message.create_system(
                room,
                "Chat ochildi.",
                sender=request.user,
                scope=get_token_scope(request),
            )

        return Response(
            ChatRoomDetailSerializer(room, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(summary="Chat xabarlari (paginated)")
    @action(
        detail=True,
        methods=["get"],
        url_path="messages",
        pagination_class=MessagePagination,
    )
    def messages(self, request, pk=None):
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        qs = Message.objects.filter(room=room, is_deleted=False).select_related(
            "sender"
        )
        # Marketplace privacy: doctor bu room'ning doctor'i bo'lsa va cutoff
        # o'rnatilgan bo'lsa — xariddan OLDINGI (AI thread) xabarlarni ko'rmaydi.
        # Bemor har doim to'liq tarixni ko'radi (filtrsiz).
        if (
            room.doctor_visible_from
            and room.doctor_id
            and room.doctor
            and room.doctor.user_id == request.user.id
        ):
            qs = qs.filter(created_at__gte=room.doctor_visible_from)
        paginator = MessagePagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = MessageSerializer(page, many=True)
        resp = paginator.get_paginated_response(serializer.data)
        # AI-rejim limit holati (tarifsiz bemorга) — chat ochilganda limit banner uchun.
        # AI-rejim bo'lmasa null.
        from app.chat.ai.gate import ai_usage_state

        resp.data["ai_usage"] = ai_usage_state(room, request.user)
        return resp

    @extend_schema(summary="Fayl yuklash uchun presigned URL")
    @action(detail=True, methods=["post"], url_path="upload-url")
    def upload_url(self, request, pk=None):
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        serializer = UploadURLSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_name = serializer.validated_data["file_name"]
        file_type = serializer.validated_data["file_type"]
        file_size = serializer.validated_data["file_size"]

        # application/octet-stream kelsa file extension dan MIME type aniqlash
        if file_type == "application/octet-stream" and file_name:
            guessed_type, _ = mimetypes.guess_type(file_name)
            if guessed_type:
                file_type = guessed_type

        if file_size > settings.CHAT_MAX_FILE_SIZE:
            return Response(
                {
                    "detail": (
                        f"Fayl hajmi {settings.CHAT_MAX_FILE_SIZE // (1024 * 1024)}MB "
                        f"dan oshmasligi kerak"
                    )
                },
                status=400,
            )
        if file_type not in settings.CHAT_ALLOWED_FILE_TYPES:
            return Response(
                {"detail": f"Ruxsat etilmagan fayl turi: {file_type}"},
                status=400,
            )

        file_key = generate_file_key(room.id, file_name)
        upload_url_str = generate_upload_url(file_key, file_type)

        return Response(
            {
                "upload_url": upload_url_str,
                "file_key": file_key,
                "content_type": file_type,
                "expires_in": 900,
            }
        )

    @extend_schema(summary="Barcha xabarlarni o'qilgan qilish")
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        updated = (
            Message.objects.filter(room=room, is_read=False, is_deleted=False)
            .exclude(sender=request.user)
            .update(is_read=True, read_at=timezone.now())
        )

        return Response({"updated": updated})

    @extend_schema(
        summary="Ovozli xabarni matnga aylantirish (STT, faqat bemor ovozi)",
        request=None,
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="messages/(?P<message_id>[0-9]+)/transcribe",
    )
    def transcribe_message(self, request, pk=None, message_id=None):
        """On-demand STT — bemor ovozli xabarini Gemini bilan matnga.

        Natija `Message.transcript`'ga saqlanadi (cache) — qayta so'rovda Gemini
        chaqirilmaydi. Faqat bemor ovozlari (doctor o'qishi uchun)."""
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        msg = Message.objects.filter(
            id=message_id, room=room, is_deleted=False
        ).first()
        if not msg:
            return Response({"detail": "Xabar topilmadi"}, status=404)

        if msg.message_type != Message.MessageType.AUDIO:
            return Response({"detail": "Bu ovozli xabar emas."}, status=400)

        # Faqat BEMOR ovozi — doctor o'z ovozini transkripsiya qilmaydi.
        is_patient_voice = (
            msg.sender_scope == Message.SenderScope.PATIENT
            or bool(room.patient_id and room.patient.user_id == msg.sender_id)
        )
        if not is_patient_voice:
            return Response(
                {"detail": "Faqat bemor ovozli xabarlari transkripsiya qilinadi."},
                status=400,
            )

        # Web webm hali m4a'ga transcode bo'lmagan — biroz kutish kerak.
        if msg.audio_status == Message.AudioStatus.PENDING:
            return Response(
                {"detail": "Audio hali tayyorlanmoqda, biroz kuting."}, status=409
            )

        # Cache — allaqachon transkript bor, Gemini chaqirmaymiz.
        if msg.transcript_status == Message.TranscriptStatus.READY and msg.transcript:
            return Response(
                {"transcript": msg.transcript, "transcript_status": "ready"}
            )

        from ..transcribe import transcribe_audio_message

        try:
            text = transcribe_audio_message(msg)
        except Exception as exc:
            Message.objects.filter(id=msg.id).update(
                transcript_status=Message.TranscriptStatus.FAILED
            )
            logger.warning("STT xato msg=%s: %s", msg.id, exc)
            return Response(
                {"detail": "Transkripsiya qilib bo'lmadi. Qaytadan urinib ko'ring."},
                status=502,
            )

        Message.objects.filter(id=msg.id).update(
            transcript=text, transcript_status=Message.TranscriptStatus.READY
        )
        return Response({"transcript": text, "transcript_status": "ready"})

    # --- Call actions ---

    def _get_room_and_callee(self, request, pk):
        """Room va callee'ni topadi. Xato bo'lsa (None, None, error_response)."""
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return None, None, Response({"detail": "Chat topilmadi"}, status=404)

        callee = room.participants.exclude(id=request.user.id).first()
        if not callee:
            # Dual-role user (Yandex Taxi identity: bir User ham doctor, ham
            # patient) o'zining patient app'idagi akkauntiga qo'ng'iroq qila
            # oladi. Callee — o'zi: push callee_scope (patient) bo'yicha patient
            # app'ga boradi (doctor web'ga emas), LiveKit identity scope+session
            # bilan unique. Bir XIL jismoniy device bloki quyida saqlanadi.
            if room.participants.filter(id=request.user.id).exists():
                callee = request.user
            else:
                return None, None, Response(
                    {"detail": "Suhbatdosh topilmadi"}, status=400
                )

        # Bitta jismoniy device'da o'ziga o'zi qo'ng'iroq blokrovkasi.
        # Caller'ning device_id (X-Device-Id header'idan yoki body'dan) callee'ning
        # ro'yxatda turgan DeviceToken'lardan birida mavjud bo'lsa — bir xil
        # telefon. Mikrofon/speaker konflikti, mantiqsiz UX. Boshqa device
        # (telefon/tablet, telefon/web) — mumkin (cheklanmagan).
        caller_device_id = (
            request.headers.get("X-Device-Id")
            or request.data.get("device_id")
            or ""
        ).strip()
        if caller_device_id:
            same_device = DeviceToken.objects.filter(
                user=callee,
                device_id=caller_device_id,
                is_active=True,
            ).exists()
            if same_device:
                return None, None, Response(
                    {
                        "detail": (
                            "Bitta telefonda o'zingiz bilan qo'ng'iroq qilolmaysiz. "
                            "Boshqa device'dan urinib ko'ring."
                        )
                    },
                    status=400,
                )

        return room, callee, None

    @extend_schema(
        request=CallInitSerializer,
        summary="Qo'ng'iroq boshlash (video/audio)",
        description="LiveKit room yaratadi, caller'ga token qaytaradi, callee'ga push + WebSocket yuboradi.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="call",
        throttle_classes=[CallStartThrottle],
    )
    def call(self, request, pk=None):
        room, callee, err = self._get_room_and_callee(request, pk)
        if err:
            return err

        serializer = CallInitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        call_type = serializer.validated_data["call_type"]

        lk_room_name = generate_room_name()

        # LiveKit room'ni SINXRON yaratamiz — shunda caller token'ida room_create
        # grant'i KERAK EMAS (xavfsizlik: room_create resurs-abuse vektori).
        # Sinxron yaratish muvaffaqiyatsiz bo'lsa → async backup + token'da
        # room_create fallback (qo'ng'iroq baribir ishlasin).
        room_ready = False
        try:
            create_room(lk_room_name)
            room_ready = True
        except Exception:
            try:
                create_livekit_room.delay(lk_room_name, None)
            except Exception:
                pass

        # CallSession yaratish — caller/callee scope JWT'dan
        caller_scope = get_token_scope(request)

        # XAVFSIZLIK/TOCTOU: aktiv-qo'ng'iroq tekshiruvi va session yaratishni
        # bitta atomic blok ichida room qatorini select_for_update bilan qulflab
        # bajaramiz. Aks holda ikki parallel so'rov (double-tap) ikkalasi ham
        # active_call=None ko'rib IKKI RINGING session + IKKI ring yaratardi.
        try:
            with transaction.atomic():
                ChatRoom.objects.select_for_update().get(pk=room.pk)
                active_call = CallSession.objects.filter(
                    room=room,
                    status__in=[
                        CallSession.Status.RINGING,
                        CallSession.Status.ACTIVE,
                    ],
                ).first()
                if active_call:
                    return Response(
                        {"detail": "Bu chatda hozir aktiv qo'ng'iroq mavjud."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                session = CallSession.objects.create(
                    room=room,
                    caller=request.user,
                    callee=callee,
                    caller_scope=caller_scope,
                    callee_scope=_other_participant_scope(room, caller_scope),
                    call_type=call_type,
                    room_name=lk_room_name,
                )
        except ChatRoom.DoesNotExist:
            return Response({"detail": "Chat topilmadi"}, status=404)

        # Caller token — scope + session marker (bir user multi-device,
        # identity collision yo'q)
        token = create_token(
            room_name=lk_room_name,
            participant_name=request.user.full_name or str(request.user.id),
            participant_identity=build_identity(
                request.user.id, caller_scope or "patient"
            ),
            allow_create=not room_ready,
        )

        # Incoming call push — callee'ga (iOS VoIP/CallKit + Android FCM)
        caller_name = request.user.full_name or "Foydalanuvchi"
        caller_avatar = (
            generate_download_url(request.user.avatar) if request.user.avatar else ""
        )
        call_label = "video" if call_type == "video" else "audio"
        callee_app_scope = session.callee_scope or None

        try:
            # iOS VoIP (PushKit → CallKit incoming call screen)
            send_voip_call_push.delay(
                callee.id,
                {
                    "aps": {
                        "alert": f"Incoming call from {caller_name}",
                        "sound": "default",
                    },
                    "call_id": session.id,
                    "call_session_id": session.id,
                    "caller_id": request.user.id,
                    "caller_name": caller_name,
                    "caller_avatar_url": caller_avatar or "",
                    "room_id": str(room.id),
                    "room_name": lk_room_name,
                    "call_type": call_type,
                },
                app_scope=callee_app_scope,
            )

            # Android/Web — FCM high priority (data-only). Title catalog'dan
            # callee tilida render qilinadi (settings yo'q bo'lsa fallback uz).
            callee_lang = (
                getattr(getattr(callee, "settings", None), "language", None) or "uz"
            )
            ic_title, ic_body = render_notif(
                "incoming_call",
                callee_lang,
                params={"name": caller_name, "call_type": call_label},
            )
            send_push_to_user.delay(
                user_id=callee.id,
                title=ic_title,
                body=ic_body,
                data={
                    "type": "incoming_call",
                    "call_session_id": str(session.id),
                    "caller_id": str(request.user.id),
                    "caller_name": caller_name,
                    "caller_avatar_url": caller_avatar or "",
                    "call_type": call_type,
                    "room_id": str(room.id),
                    "room_name": lk_room_name,
                },
                data_only=True,
                app_scope=callee_app_scope,
            )
        except Exception:
            pass

        # WebSocket orqali callee'ga incoming_call
        _broadcast_ws(
            room.id,
            {
                "type": "call.event",
                "event": "incoming_call",
                "call_session_id": session.id,
                "call_type": call_type,
                "caller_id": request.user.id,
                "caller_name": request.user.full_name or "",
            },
        )

        # Auto-miss (60s) + unreachable check (20s — delivery-ack kelmasa).
        try:
            check_missed_call.apply_async(args=[session.id], countdown=60)
            check_unreachable_call.apply_async(args=[session.id], countdown=20)
        except Exception:
            pass

        return Response(
            {
                "call_session_id": session.id,
                "call_type": call_type,
                "status": session.status,
                "room_name": lk_room_name,
                "livekit_url": settings.LIVEKIT_URL,
                "token": token,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Qo'ng'iroqni qabul qilish")
    @action(detail=True, methods=["post"], url_path="call/accept")
    def accept_call(self, request, pk=None):
        # Eng so'nggi (har qanday status) sessiyani topamiz — diagnostika uchun.
        # CallSession Meta.ordering = ['-created_at'] → first() eng yangi.
        latest = CallSession.objects.filter(room_id=pk, callee=request.user).first()

        if not latest:
            return Response(
                {
                    "detail": "Kutilayotgan qo'ng'iroq topilmadi.",
                    "reason": "no_session",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Idempotent: agar allaqachon ACTIVE bo'lsa (multi-tap, retry) — hozirgi
        # token bilan qaytaramiz.
        if latest.status == CallSession.Status.ACTIVE:
            session = latest
        elif latest.status == CallSession.Status.RINGING:
            session = latest
            session.status = CallSession.Status.ACTIVE
            session.started_at = timezone.now()
            session.save(update_fields=["status", "started_at"])
        else:
            return Response(
                {
                    "detail": "Qo'ng'iroq allaqachon yakunlangan.",
                    "reason": "already_ended",
                    "status": latest.status,
                    "ended_at": (
                        latest.ended_at.isoformat() if latest.ended_at else None
                    ),
                    "call_session_id": latest.id,
                },
                status=status.HTTP_410_GONE,
            )

        # Callee — odatda boshqa scope'da (caller patient bo'lsa, callee doctor)
        callee_scope_local = (
            session.callee_scope or get_token_scope(request) or "patient"
        )
        # Room call boshlanishida yaratilgan — callee token'ida room_create kerak emas
        token = create_token(
            room_name=session.room_name,
            participant_name=request.user.full_name or str(request.user.id),
            participant_identity=build_identity(request.user.id, callee_scope_local),
            allow_create=False,
        )

        _broadcast_ws(
            pk,
            {
                "type": "call.event",
                "event": "call_accepted",
                "call_session_id": session.id,
            },
        )

        return Response(
            {
                "call_session_id": session.id,
                "room_name": session.room_name,
                "livekit_url": settings.LIVEKIT_URL,
                "token": token,
            }
        )

    @extend_schema(exclude=True)
    @action(detail=True, methods=["post"], url_path="call/ringing")
    def call_ringing(self, request, pk=None):
        """Callee qurilmasi incoming UI ko'rsatganda delivery-ack (ISH-1).

        ringing_at saqlanadi + caller'ga WS `call_ringing` (UI "Ulanmoqda" →
        "Jiringlamoqda"). Idempotent (multi-device/retry). Caller o'zi ack
        yubormasin (403). Yakunlangan session → 410 (qurilma incoming UI'ni
        dismiss qiladi). Bearer token + X-Device-Id bilan ishlaydi."""
        session_id = request.data.get("call_session_id")
        if session_id:
            session = CallSession.objects.filter(id=session_id, room_id=pk).first()
        else:
            # session_id push'da kelmagan (bo'sh {}) — room'dagi joriy RINGING
            # sessionni topamiz (call action dublikat RINGING yaratmaydi).
            session = (
                CallSession.objects.filter(
                    room_id=pk, status=CallSession.Status.RINGING
                )
                .order_by("-created_at")
                .first()
            )
        if not session:
            return Response({"detail": "Topilmadi"}, status=404)
        if session.callee_id != request.user.id:
            return Response(status=403)
        # Yakunlangan (missed/cancelled/rejected/ended) → 410
        if session.status != CallSession.Status.RINGING:
            return Response({"status": session.status}, status=410)
        # Idempotent: birinchi ack → ringing_at + WS; takror ack → no-op 200
        if session.ringing_at is None:
            session.ringing_at = timezone.now()
            session.save(update_fields=["ringing_at"])
            try:
                async_to_sync(get_channel_layer().group_send)(
                    f"chat_{session.room_id}",
                    {
                        "type": "call.event",
                        "event": "call_ringing",
                        "call_session_id": session.id,
                    },
                )
            except Exception:
                pass
        return Response({"status": "ringing"})

    @extend_schema(summary="Qo'ng'iroqni rad etish")
    @action(detail=True, methods=["post"], url_path="call/reject")
    def reject_call(self, request, pk=None):
        session = CallSession.objects.filter(
            room_id=pk, callee=request.user, status=CallSession.Status.RINGING
        ).first()

        if not session:
            return Response(
                {"detail": "Kutilayotgan qo'ng'iroq topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session.status = CallSession.Status.REJECTED
        session.ended_at = timezone.now()
        session.save(update_fields=["status", "ended_at"])

        Message.create_system(
            int(pk),
            session.system_message_rejected(),
            sender=session.caller,
            scope=session.caller_scope,
        )

        _broadcast_ws(
            pk,
            {
                "type": "call.event",
                "event": "call_rejected",
                "call_session_id": session.id,
            },
        )

        return Response(
            {"detail": "Qo'ng'iroq rad etildi", "call_session_id": session.id}
        )

    @extend_schema(summary="Qo'ng'iroqni tugatish (ikki tomon ham)")
    @action(detail=True, methods=["post"], url_path="call/end")
    def end_call(self, request, pk=None):
        session = (
            CallSession.objects.filter(
                room_id=pk,
                status__in=[CallSession.Status.RINGING, CallSession.Status.ACTIVE],
            )
            .filter(Q(caller=request.user) | Q(callee=request.user))
            .first()
        )

        if not session:
            return Response(
                {"detail": "Aktiv qo'ng'iroq topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now()
        old_status = session.status

        if session.status == CallSession.Status.ACTIVE:
            session.status = CallSession.Status.COMPLETED
            if session.started_at:
                session.duration = int((now - session.started_at).total_seconds())
        else:
            session.status = CallSession.Status.CANCELLED

        session.ended_at = now
        session.save(update_fields=["status", "ended_at", "duration"])
        # Caller RINGING paytida end qildi → callee qurilmasidagi CallKit/incoming
        # UI'ni yopish uchun cancel push (ISH-4).
        if old_status == CallSession.Status.RINGING:
            _send_call_cancel_push(session)
        # Diagnostic: kim, qachon, qaysi vaqt oralig'ida tugatdi
        elapsed_ms = (
            int((now - session.created_at).total_seconds() * 1000)
            if session.created_at
            else None
        )
        logger.info(
            "call.end_call session=%s room=%s by_user=%s old_status=%s new_status=%s elapsed_ms=%s",
            session.id,
            pk,
            request.user.id,
            old_status,
            session.status,
            elapsed_ms,
        )

        Message.create_system(
            int(pk),
            session.system_message_finished(),
            sender=session.caller,
            scope=session.caller_scope,
        )

        _broadcast_ws(
            pk,
            {
                "type": "call.event",
                "event": "call_ended",
                "call_session_id": session.id,
                "duration": session.duration,
            },
        )

        return Response({"detail": "Qo'ng'iroq tugadi", "duration": session.duration})

    @extend_schema(summary="Qo'ng'iroqlar tarixi")
    @action(detail=True, methods=["get"], url_path="call-history")
    def call_history(self, request, pk=None):
        room = self.get_queryset().filter(id=pk).first()
        if not room:
            return Response({"detail": "Chat topilmadi"}, status=404)

        sessions = CallSession.objects.filter(room=room).select_related(
            "caller", "callee"
        )[:50]
        return Response(CallSessionSerializer(sessions, many=True).data)


