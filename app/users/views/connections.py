from .common import *  # noqa: F401,F403 - importlar + AVATAR_* + top-level helperlar


class ConnectionMixin:
    """Doctor<->Patient ulanishlar — UserViewSet mixin."""

    @extend_schema(
        request=LinkDoctorSerializer,
        responses=UserSerializer,
        summary="Doctorga bog'lanish (QR / referral code orqali)",
        description="Patient doctor referral code ni yuboradi, referred_by o'rnatiladi.",
    )
    @action(detail=False, methods=["post"], url_path="me/link-doctor")
    def link_doctor(self, request):
        serializer = LinkDoctorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Referral code unique, role tekshiruvi yo'q — admin bo'lib ketgan doctor ham bog'lanishi mumkin
        doctor = User.objects.get(
            referral_code=serializer.validated_data["referral_code"],
        )
        request.user.referred_by = doctor
        request.user.save(update_fields=["referred_by"])

        return Response(UserSerializer(request.user).data)

    @extend_schema(
        summary="Mening shifokorlarim",
        description="Telefon orqali qo'shilgan + referral orqali birikkan doktorlar.",
    )
    @action(detail=False, methods=["get"], url_path="me/my-doctors")
    def my_doctors(self, request):
        dp_doctor_ids = DoctorPatient.objects.filter(
            patient=request.user,
            status=DoctorPatient.Status.ACCEPTED,
        ).values_list("doctor__user_id", flat=True)

        referred_ids = []
        if (
            request.user.referred_by
            and request.user.referred_by.role == User.Role.DOCTOR
        ):
            referred_ids.append(request.user.referred_by_id)

        all_ids = set(dp_doctor_ids) | set(referred_ids)

        patient_profile = getattr(request.user, "patient_profile", None)
        if patient_profile is not None:
            room_qs = ChatRoom.objects.filter(
                patient=patient_profile,
                doctor=OuterRef("pk"),
                room_type=ChatRoom.RoomType.CONSULTATION,
                is_active=True,
            )
            last_chat_subq = Subquery(
                room_qs.values("updated_at")[:1],
                output_field=DateTimeField(),
            )
            unread_subq = Subquery(
                Message.objects.filter(
                    room__patient=patient_profile,
                    room__doctor=OuterRef("pk"),
                    room__room_type=ChatRoom.RoomType.CONSULTATION,
                    room__is_active=True,
                    is_read=False,
                    is_deleted=False,
                )
                .exclude(sender=request.user)
                .order_by()
                .values("room")
                .annotate(c=Count("id"))
                .values("c")[:1],
                output_field=IntegerField(),
            )
        else:
            last_chat_subq = None
            unread_subq = None

        doctors = (
            DoctorProfile.objects.filter(
                user_id__in=all_ids, user__is_active=True
            )
            .select_related("user", "specialty")
            .annotate(
                _rating_avg=Avg("reviews__rating"),
                _total_reviews=Count("reviews", distinct=True),
            )
        )
        if last_chat_subq is not None:
            doctors = doctors.annotate(
                _last_chat_at=last_chat_subq,
                _unread_count=Coalesce(unread_subq, 0),
            ).order_by(F("_last_chat_at").desc(nulls_last=True), "id")
        else:
            doctors = doctors.order_by("id")

        # Patient shu doctorlarda eng oxirgi (eng kech tugaydigan) tarifi
        purchase_by_doctor = {}
        for pur in (
            DoctorTariffPurchase.objects.filter(
                patient=request.user, doctor__in=doctors
            )
            .select_related("tariff")
            .order_by("-expires_at")
        ):
            purchase_by_doctor.setdefault(pur.doctor_id, pur)

        doctor_user_to_id = {d.user_id: d.id for d in doctors}
        patients_per_doctor: dict[int, set[int]] = defaultdict(set)
        for doc_id, pat_id in DoctorPatient.objects.filter(
            doctor_id__in=doctor_user_to_id.values(),
            status=DoctorPatient.Status.ACCEPTED,
        ).values_list("doctor_id", "patient_id"):
            patients_per_doctor[doc_id].add(pat_id)
        for doc_user_id, referred_user_id in User.objects.filter(
            referred_by_id__in=doctor_user_to_id.keys()
        ).values_list("referred_by_id", "id"):
            doc_id = doctor_user_to_id.get(doc_user_id)
            if doc_id is not None:
                patients_per_doctor[doc_id].add(referred_user_id)
        total_patients_map = {
            doc_id: len(pset) for doc_id, pset in patients_per_doctor.items()
        }

        return Response(
            DoctorListSerializer(
                doctors,
                many=True,
                context={
                    "purchase_by_doctor": purchase_by_doctor,
                    "total_patients_map": total_patients_map,
                },
            ).data
        )

    @extend_schema(
        summary="Telefon orqali shifokorga so'rov yuborish",
        description=(
            "Bemor shifokor telefon raqamini kiritadi. Doctor tomonida pending "
            "so'rov ko'rinadi, doctor accept/decline qilishi kerak. "
            "Self-add (o'zini o'ziga) — DoctorProfile avtomatik yaratiladi va "
            "auto-accepted."
        ),
    )
    @action(detail=False, methods=["post"], url_path="me/add-doctor")
    def add_doctor(self, request):
        # QR/referral oqimi `referral_code` yuboradi (doctor QR'i skaner qilinganda),
        # eski oqim `phone`. Ikkalasini ham qabul qilamiz → doctorni topib ulaymiz.
        referral_code = (request.data.get("referral_code") or "").strip()
        if referral_code:
            doctor_user = User.objects.filter(referral_code=referral_code).first()
            if not doctor_user:
                return Response({"detail": "Noto'g'ri referral code."}, status=400)
        else:
            serializer = AddByPhoneSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            doctor_user = User.objects.get(phone=serializer.validated_data["phone"])

        # Self-add — har user doctor profile yarata oladi (admin moderatsiyasi
        # boshqa joylarda ishlaydi). Aks holda — mavjud profilni topish.
        self_add = doctor_user == request.user
        if self_add:
            profile, _ = DoctorProfile.objects.get_or_create(
                user=doctor_user, defaults={"is_verified": False}
            )
        else:
            profile = getattr(doctor_user, "doctor_profile", None)
            if not profile:
                return Response(
                    {"detail": "Bu foydalanuvchining shifokor profili mavjud emas."},
                    status=400,
                )

        # Self-add — avtomatik accepted. Aks holda — pending (doctor accept qilishi kerak)
        defaults = {
            "added_by": DoctorPatient.AddedBy.PATIENT,
            "requested_by": DoctorPatient.AddedBy.PATIENT,
            "status": (
                DoctorPatient.Status.ACCEPTED
                if self_add
                else DoctorPatient.Status.PENDING
            ),
        }
        if self_add:
            defaults["responded_at"] = timezone.now()

        dp, created = DoctorPatient.objects.get_or_create(
            doctor=profile,
            patient=request.user,
            defaults=defaults,
        )

        # Agar oldin declined bo'lsa — qayta pending qilamiz
        re_requested = False
        if not created and dp.status == DoctorPatient.Status.DECLINED:
            dp.status = DoctorPatient.Status.PENDING
            dp.requested_by = DoctorPatient.AddedBy.PATIENT
            dp.responded_at = None
            dp.save(update_fields=["status", "requested_by", "responded_at"])
            re_requested = True

        # Doctor'ga push: patient sizga bog'lanish so'rovi yubordi.
        # Self-add (auto-accepted) yoki mavjud accepted/pending yozuv uchun push yo'q.
        should_notify = not self_add and (
            (created and dp.status == DoctorPatient.Status.PENDING) or re_requested
        )
        if should_notify:
            try:
                notify_by_key_user.delay(
                    user_id=profile.user_id,
                    type=Notification.Type.CONNECTION_REQUEST,
                    key="connection_request",
                    params={
                        "name": request.user.full_name or "Bemor",
                    },
                    data={
                        "connection_id": str(dp.id),
                        "patient_id": str(request.user.id),
                    },
                    app_scope="doctor",
                )
            except Exception:
                pass

        return Response(
            DoctorPatientSerializer(dp).data,
            status=201 if created else 200,
        )

    @extend_schema(
        summary="Mening bog'lanish so'rovlarim (patient uchun)",
        description=(
            "Doctor'lardan kelgan pending so'rovlarni qaytaradi. "
            "Har bir so'rov uchun accept/decline API chaqirish mumkin."
        ),
    )
    @action(detail=False, methods=["get"], url_path="me/connections/pending")
    def pending_connections(self, request):
        qs = (
            DoctorPatient.objects.filter(
                patient=request.user,
                status=DoctorPatient.Status.PENDING,
                requested_by=DoctorPatient.AddedBy.DOCTOR,
            )
            .select_related("doctor__user", "doctor__specialty")
            .order_by("-created_at")
        )
        return Response(DoctorPatientSerializer(qs, many=True).data)

    def _respond_to_connection(self, connection_id, new_status):
        """Doctor'dan kelgan pending so'rovni accept yoki decline qilish."""
        dp = (
            DoctorPatient.objects.filter(
                id=connection_id,
                patient=self.request.user,
                status=DoctorPatient.Status.PENDING,
                requested_by=DoctorPatient.AddedBy.DOCTOR,
            )
            .select_related("doctor__user")
            .first()
        )
        if not dp:
            return Response(
                {"detail": "So'rov topilmadi yoki sizga tegishli emas."},
                status=404,
            )
        dp.status = new_status
        dp.responded_at = timezone.now()
        dp.save(update_fields=["status", "responded_at"])

        # Doctor (so'rov egasi) ga push: patient accept yoki decline qildi
        is_accepted = new_status == DoctorPatient.Status.ACCEPTED
        try:
            notify_by_key_user.delay(
                user_id=dp.doctor.user_id,
                type=(
                    Notification.Type.CONNECTION_ACCEPTED
                    if is_accepted
                    else Notification.Type.CONNECTION_DECLINED
                ),
                key=("connection_accepted" if is_accepted else "connection_declined"),
                params={
                    "name": self.request.user.full_name or "Bemor",
                },
                data={
                    "connection_id": str(dp.id),
                    "patient_id": str(self.request.user.id),
                },
                app_scope="doctor",
            )
        except Exception:
            pass

        return Response(DoctorPatientSerializer(dp).data)

    @extend_schema(
        summary="Bog'lanish so'rovini qabul qilish (patient)",
        description="Doctor'dan kelgan pending so'rovni accepted qiladi.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=r"me/connections/(?P<connection_id>\d+)/accept",
    )
    def accept_connection(self, request, connection_id=None):
        return self._respond_to_connection(connection_id, DoctorPatient.Status.ACCEPTED)

    @extend_schema(
        summary="Bog'lanish so'rovini rad etish (patient)",
        description="Doctor'dan kelgan pending so'rovni declined qiladi.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=r"me/connections/(?P<connection_id>\d+)/decline",
    )
    def decline_connection(self, request, connection_id=None):
        return self._respond_to_connection(connection_id, DoctorPatient.Status.DECLINED)

    @extend_schema(
        summary="Shifokorni ro'yxatdan olib tashlash (disconnect)",
        description=(
            "Bemor o'z shifokorlar ro'yxatidan disconnect qiladi. "
            "Ham DoctorPatient yozuvini o'chiradi, ham referred_by link'ni "
            "tozalaydi (agar shu doctor'ga qaratilgan bo'lsa). Shunda my-doctors "
            "ro'yxatida qaytmaydi."
        ),
    )
    @action(
        detail=False,
        methods=["delete"],
        url_path=r"me/doctors/(?P<doctor_id>\d+)/disconnect",
    )
    def disconnect_doctor(self, request, doctor_id=None):
        try:
            doctor_id_int = int(str(doctor_id).strip().strip('"').strip("'"))
        except (TypeError, ValueError):
            return Response({"detail": "Noto'g'ri shifokor ID."}, status=400)

        # Ikki yozuv operatsiyasi (delete + referred_by tozalash) atomic bo'lishi
        # kerak — aks holda ikkinchisi fail bersa qisman holat qoladi.
        with transaction.atomic():
            # 1. DoctorPatient yozuvlarini o'chirish (pending, accepted, declined — hammasini)
            dp_deleted, _ = DoctorPatient.objects.filter(
                patient=request.user, doctor__user_id=doctor_id_int
            ).delete()

            # 2. Referral link'ni tozalash (agar shu doctor'ga qaratilgan bo'lsa)
            referral_cleared = False
            if (
                request.user.referred_by_id
                and request.user.referred_by_id == doctor_id_int
            ):
                request.user.referred_by = None
                request.user.save(update_fields=["referred_by"])
                referral_cleared = True

        if not dp_deleted and not referral_cleared:
            return Response(
                {"detail": "Bu shifokor sizning ro'yxatingizda yo'q."}, status=404
            )

        return Response(status=204)
