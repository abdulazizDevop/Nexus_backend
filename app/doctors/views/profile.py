from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar + helperlar
from .common import _allowed_patient_ids


@extend_schema(tags=["Doctor - Profil"])
class DoctorProfileViewSet(viewsets.ModelViewSet):
    """Doctor profili — o'zi tahrirlaydi, hammaga ko'rinadi"""

    queryset = (
        DoctorProfile.objects.select_related("user", "specialty")
        .prefetch_related("certificates", "specialties")
        .annotate(
            _rating_avg=models.Avg("reviews__rating"),
            _total_reviews=models.Count("reviews", distinct=True),
        )
    )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DoctorProfile.objects.none()
        qs = super().get_queryset()
        # Self-delete qilingan (is_active=False) yoki doctor-profili o'chirilgan
        # (is_deleted=True — User bemor sifatida tirik) doctorlar public
        # ro'yxatda ko'rinmaydi. Tarixiy yozuvlar (appointment, payment) saqlanadi.
        return qs.filter(user__is_active=True, is_deleted=False)

    def get_serializer_class(self):
        # me() action serializerlarni o'zi qo'lda yaratadi — bu yerda branch shart
        # emas (get_serializer_class()'ni chaqirmaydi).
        if self.action == "list":
            return DoctorListSerializer
        return DoctorProfileSerializer

    @extend_schema(summary="Barcha doktorlar ro'yxati")
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        profiles = list(page) if page is not None else list(queryset)

        # N+1 oldini olish: total_patients property har bir doctor uchun 2 ta
        # so'rov qiladi (User.referred_by + DoctorPatient). Buni listda bir
        # martalik 2 ta agregat so'rovga aylantirib, contextga xarita beramiz.
        ids_by_doctor = patient_ids_by_doctor(profiles)
        total_patients_map = {
            pid: len(ids) for pid, ids in ids_by_doctor.items()
        }

        context = self.get_serializer_context()
        context["total_patients_map"] = total_patients_map
        serializer = self.get_serializer_class()(profiles, many=True, context=context)

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        summary="Marketplace — 'Barcha shifokorlar' ro'yxati",
        parameters=[
            OpenApiParameter("search", str, description="Ism yoki mutaxassislik (qisman, case-insensitive)"),
            OpenApiParameter("specialty", int, description="Mutaxassislik id bo'yicha filtr"),
            OpenApiParameter("min_rating", float, description="Minimal reyting (mas. 4.5)"),
            OpenApiParameter("page", int, description="Sahifa"),
        ],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="marketplace",
        permission_classes=[IsAuthenticated],
    )
    def marketplace(self, request):
        """Bemor uchun 'Barcha shifokorlar' — verified + marketplace_visible.

        Barcha hisoblanadigan maydonlar (reviews_count, min_tariff_price,
        connection_status, has_active_tariff) ANNOTATSIYA/Subquery/Exists orqali —
        N+1 yo'q. connection_status/has_active_tariff so'rovchi bemorga nisbatan.
        """
        user = request.user
        now = timezone.now()
        qs = (
            DoctorProfile.objects.select_related("user")
            .prefetch_related("specialties")
            .filter(
                user__is_active=True,
                is_deleted=False,
                is_verified=True,
                marketplace_visible=True,
            )
            .annotate(
                _rating_avg=models.Avg("reviews__rating"),
                _total_reviews=Count("reviews", distinct=True),
                # Xom (chegirmasiz) minimal APPROVED+aktiv tarif narxi; yo'q → null.
                _min_tariff_price=Min(
                    "tariffs__price",
                    filter=Q(
                        tariffs__status=DoctorTariff.Status.APPROVED,
                        tariffs__is_active=True,
                    ),
                ),
                _connection_status=Subquery(
                    DoctorPatient.objects.filter(
                        doctor=OuterRef("pk"), patient=user
                    ).values("status")[:1]
                ),
                _has_active_tariff=Exists(
                    DoctorTariffPurchase.objects.filter(
                        doctor=OuterRef("pk"), patient=user, expires_at__gt=now
                    )
                ),
            )
        )

        search = (request.query_params.get("search") or "").strip()
        if search:
            # Ism (majburiy) + mutaxassislik nomi (JSONField — matn ichida qidiradi).
            qs = qs.filter(
                Q(user__full_name__icontains=search)
                | Q(specialties__name__icontains=search)
            )

        specialty = request.query_params.get("specialty")
        if specialty and specialty.isdigit():
            qs = qs.filter(specialties__id=int(specialty))

        min_rating = request.query_params.get("min_rating")
        if min_rating:
            try:
                qs = qs.filter(_rating_avg__gte=float(min_rating))
            except (TypeError, ValueError):
                pass

        # Default: reyting kamayish (reytingsizlar oxirida), keyin -id (barqaror).
        # Agregat annotatsiyalar GROUP BY doctor.id beradi — M2M join dublikat yaratmaydi.
        qs = qs.order_by(F("_rating_avg").desc(nulls_last=True), "-id")

        page = self.paginate_queryset(qs)
        rows = page if page is not None else list(qs)
        # total_patients — butun sahifa uchun 1-2 agregat so'rov (N+1 yo'q),
        # DoctorListSerializer bilan bir xil context-map naqsh. Konsultatsiya
        # maydonlari DoctorProfile ustunlari — qatorning o'zida keladi.
        from ..models import patient_ids_by_doctor

        context = self.get_serializer_context()
        context["total_patients_map"] = {
            pid: len(ids) for pid, ids in patient_ids_by_doctor(rows).items()
        }
        serializer = MarketplaceDoctorSerializer(rows, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(summary="Doctor profili (batafsil)")
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

    @extend_schema(
        request=DoctorProfileUpdateSerializer,
        responses=DoctorProfileSerializer,
        summary="O'z profilini ko'rish va tahrirlash",
        description="GET: to'liq profil. PATCH: profilni yangilash.",
    )
    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        profile, _ = DoctorProfile.objects.get_or_create(user=request.user)

        if request.method == "PATCH":
            serializer = DoctorProfileUpdateSerializer(
                profile, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        profile = (
            DoctorProfile.objects.select_related("user", "specialty")
            .prefetch_related("certificates", "specialties")
            .get(pk=profile.pk)
        )

        return Response(DoctorProfileSerializer(profile).data)

    @extend_schema(
        operation_id="doctors_my_patients_list",
        summary="Doctor ning bemorlar ro'yxati",
        description="Telefon orqali qo'shilgan + referral orqali birikkan bemorlar. Salomatlik ko'rsatkichlari bilan.",
    )
    @action(detail=False, methods=["get"], url_path="me/patients")
    def my_patients(self, request):
        profile = getattr(request.user, "doctor_profile", None)
        all_ids = _allowed_patient_ids(profile, request.user)

        from app.chat.models import ChatRoom, Message

        patients_qs = (
            User.objects.filter(id__in=all_ids, is_active=True)
            .select_related("settings")
            .distinct()
        )

        if profile is not None:
            room_qs = ChatRoom.objects.filter(
                patient__user_id=OuterRef("pk"),
                doctor=profile,
                room_type=ChatRoom.RoomType.CONSULTATION,
                is_active=True,
            )
            last_chat_subq = Subquery(
                room_qs.values("updated_at")[:1],
                output_field=DateTimeField(),
            )
            unread_subq = Subquery(
                Message.objects.filter(
                    room__patient__user_id=OuterRef("pk"),
                    room__doctor=profile,
                    room__room_type=ChatRoom.RoomType.CONSULTATION,
                    room__is_active=True,
                    is_read=False,
                    is_deleted=False,
                )
                .exclude(sender=request.user)
                .exclude(message_type=Message.MessageType.SYSTEM)
                .order_by()
                .values("room")
                .annotate(c=Count("id"))
                .values("c")[:1],
                output_field=IntegerField(),
            )
            patients_qs = patients_qs.annotate(
                _last_chat_at=last_chat_subq,
                _unread_count=Coalesce(unread_subq, 0),
            ).order_by(F("_last_chat_at").desc(nulls_last=True), "id")
        else:
            patients_qs = patients_qs.order_by("id")

        patients = list(patients_qs)
        patient_ids = [p.id for p in patients]

        # Doctor sotgan eng oxirgi (eng kech tugaydigan) tarif — har bemor uchun bittadan
        purchase_by_patient = {}
        if profile:
            for pur in (
                DoctorTariffPurchase.objects.filter(
                    doctor=profile, patient_id__in=patient_ids
                )
                .select_related("tariff")
                .order_by("-expires_at")
            ):
                purchase_by_patient.setdefault(pur.patient_id, pur)

        # N+1 oldini olish: barcha bemorlar uchun salomatlik ko'rsatkichlari va
        # oxirgi kayfiyat tekshiruvini bitta query bilan olib, context'ga uzatamiz.
        indicators_by_user: dict[int, list] = {}
        checkup_by_user: dict[int, "DailySituationCheckup"] = {}

        if patient_ids:
            try:
                latest_inds = (
                    HealthIndicator.objects.filter(user_id__in=patient_ids)
                    .select_related("indicator_type")
                    .order_by("user_id", "indicator_type_id", "-date")
                    .distinct("user_id", "indicator_type_id")
                )
                for ind in latest_inds:
                    indicators_by_user.setdefault(ind.user_id, []).append(ind)
            except Exception:
                # SQLite distinct(fields) qo'llab-quvvatlamaydi — Python dedupe
                seen: dict[tuple, "HealthIndicator"] = {}
                for ind in (
                    HealthIndicator.objects.filter(user_id__in=patient_ids)
                    .select_related("indicator_type")
                    .order_by("-date")
                ):
                    key = (ind.user_id, ind.indicator_type_id)
                    if key not in seen:
                        seen[key] = ind
                for ind in seen.values():
                    indicators_by_user.setdefault(ind.user_id, []).append(ind)

            try:
                latest_checkups = (
                    DailySituationCheckup.objects.filter(user_id__in=patient_ids)
                    .order_by("user_id", "-date")
                    .distinct("user_id")
                )
                for c in latest_checkups:
                    checkup_by_user[c.user_id] = c
            except Exception:
                for c in DailySituationCheckup.objects.filter(
                    user_id__in=patient_ids
                ).order_by("-date"):
                    checkup_by_user.setdefault(c.user_id, c)

        # AI insight hisoboti — har bemor uchun eng oxirgi (ro'yxat chipida). N+1 yo'q:
        # bitta query, patient_id -> eng yangi AIHealthReport (so'nggi 30 kun ichida).
        report_by_patient = {}
        if profile and patient_ids:
            from app.health_ai.models import AIHealthReport

            recent = timezone.localdate() - timedelta(days=30)
            for rep in AIHealthReport.objects.filter(
                doctor=profile, patient_id__in=patient_ids, period_start__gte=recent
            ).order_by("patient_id", "-period_start", "-created_at"):
                report_by_patient.setdefault(rep.patient_id, rep)

        return Response(
            PatientWithHealthSerializer(
                patients,
                many=True,
                context={
                    "purchase_by_patient": purchase_by_patient,
                    "indicators_by_user": indicators_by_user,
                    "checkup_by_user": checkup_by_user,
                    "report_by_patient": report_by_patient,
                    "doctor_profile": profile,
                },
            ).data
        )

    @extend_schema(
        operation_id="doctors_my_patient_detail",
        summary="Bemor to'liq ma'lumoti",
        description="Bemor profili, salomatlik ko'rsatkichlari, muolajalar va qabullar tarixi.",
        parameters=[
            OpenApiParameter(
                name="patient_id",
                type=int,
                location=OpenApiParameter.PATH,
                required=True,
                description="Bemor user ID si",
            )
        ],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"me/patients/(?P<patient_id>\d+)",
    )
    def patient_detail(self, request, patient_id=None):
        profile = getattr(request.user, "doctor_profile", None)
        allowed_ids = _allowed_patient_ids(profile, request.user)

        if int(patient_id) not in allowed_ids:
            return Response({"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404)

        patient = User.objects.get(pk=patient_id)
        serializer = PatientDetailSerializer(
            patient, context={"request": request, "doctor_profile": profile}
        )
        return Response(serializer.data)

    @extend_schema(
        summary="Bemor kunlik hisoboti (sana bo'yicha)",
        description="?date=2026-04-02 — checkup + indicators + treatments (logs bilan)",
        parameters=[
            OpenApiParameter(
                name="patient_id",
                type=int,
                location=OpenApiParameter.PATH,
                required=True,
                description="Bemor user ID si",
            )
        ],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path=r"me/patients/(?P<patient_id>\d+)/daily-report",
    )
    def daily_report(self, request, patient_id=None):
        profile = getattr(request.user, "doctor_profile", None)
        allowed_ids = _allowed_patient_ids(profile, request.user)

        try:
            patient_id_int = int(patient_id)
        except (TypeError, ValueError):
            return Response({"detail": "Noto'g'ri patient_id."}, status=400)

        if patient_id_int not in allowed_ids:
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404
            )

        try:
            patient = User.objects.get(pk=patient_id_int)
        except User.DoesNotExist:
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404
            )

        # Sana
        date_str = request.query_params.get("date")
        if date_str:
            try:
                target_date = dt.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"detail": "Sana formati: YYYY-MM-DD"}, status=400)
        else:
            target_date = timezone.localdate()

        # 1. Checkup
        checkup = DailySituationCheckup.objects.filter(
            user=patient, date=target_date
        ).first()
        checkup_data = (
            {
                "id": checkup.id,
                "status": checkup.status,
                "status_display": checkup.get_status_display(),
                "note": checkup.note,
                "date": checkup.date.isoformat(),
            }
            if checkup
            else None
        )

        # 2. Indicators — vaqt bo'yicha kamayuvchi (eng yangisi tepada)
        indicators = (
            HealthIndicator.objects.filter(user=patient, date=target_date)
            .select_related("indicator_type")
            .order_by("-recorded_at", "-id")
        )
        lang = get_request_lang(request)
        indicators_data = [
            {
                "id": ind.id,
                "type_id": ind.indicator_type_id,
                "system_key": ind.indicator_type.system_key,
                "name": pick_translation(ind.indicator_type.name, lang),
                "value": ind.display_value,
                "unit": ind.indicator_type.unit,
                "icon": ind.indicator_type.icon,
                "value_format": ind.indicator_type.value_format,
                "date": ind.date.isoformat(),
                "recorded_at": ind.recorded_at.isoformat() if ind.recorded_at else None,
                "recorded_time": (
                    # localtime — Asia/Tashkent (aks holda UTC, 5 soat orqada chiqadi)
                    timezone.localtime(ind.recorded_at).strftime("%H:%M")
                    if ind.recorded_at
                    else None
                ),
                "source": ind.source,
            }
            for ind in indicators
        ]

        # 3. Treatments + logs
        treatments_qs = list(
            Treatment.objects.filter(user=patient).select_related("created_by")
        )

        # N+1 oldini olish: barcha treatment'lar uchun shu kunlik log'larni bitta
        # so'rovda olib, treatment_id bo'yicha guruhlaymiz (indicators/checkup
        # qismidagi map pattern kabi).
        logs_by_treatment: dict[int, list] = {}
        treatment_ids = [t.id for t in treatments_qs]
        if treatment_ids:
            for log in TreatmentLog.objects.filter(
                treatment_id__in=treatment_ids, date=target_date
            ):
                logs_by_treatment.setdefault(log.treatment_id, []).append(log)

        treatments_data = []
        for t in treatments_qs:
            if t.end_date and t.end_date < target_date:
                continue
            if t.created_at.date() > target_date:
                continue

            scheduled_times = [
                time.strftime("%H:%M") for time in t.get_scheduled_times()
            ]
            logs = logs_by_treatment.get(t.id, [])
            completed_count = sum(
                1
                for log in logs
                if log.status == TreatmentLog.Status.COMPLETED
            )
            total = len(scheduled_times) or 1
            treatments_data.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "type": t.type,
                    "type_display": t.get_type_display(),
                    "dosage": t.dosage,
                    "scheduled_times": scheduled_times,
                    "logs": [
                        {
                            "id": log.id,
                            "status": log.status,
                            "status_display": log.get_status_display(),
                        }
                        for log in logs
                    ],
                    "completion_percent": (
                        int(completed_count * 100 / total) if total else 0
                    ),
                    "created_by": (
                        t.created_by.full_name if t.created_by else None
                    ),
                    "is_deleted": False,
                }
            )

        # O'chirilgan muolajalarning saqlangan loglari (treatment=NULL, SET_NULL
        # arxiv) — muolaja o'chirilsa ham tarix kunlarida "ichildi" belgilari
        # ko'rinishda qoladi. Snapshot (title/type) bo'yicha guruhlanadi.
        archived_logs = TreatmentLog.objects.filter(
            user=patient, date=target_date, treatment__isnull=True
        )
        archived_groups: dict[tuple, list] = {}
        for log in archived_logs:
            archived_groups.setdefault(
                (log.treatment_title, log.treatment_type), []
            ).append(log)
        type_labels = dict(Treatment.Type.choices)
        for (a_title, a_type), a_logs in archived_groups.items():
            a_completed = sum(
                1 for log in a_logs if log.status == TreatmentLog.Status.COMPLETED
            )
            a_total = len(a_logs) or 1
            treatments_data.append(
                {
                    "id": None,
                    "title": a_title or "Muolaja",
                    "type": a_type,
                    "type_display": type_labels.get(a_type, a_type),
                    "dosage": "",
                    "scheduled_times": [],
                    "logs": [
                        {
                            "id": log.id,
                            "status": log.status,
                            "status_display": log.get_status_display(),
                        }
                        for log in a_logs
                    ],
                    "completion_percent": int(a_completed * 100 / a_total),
                    "created_by": None,
                    "is_deleted": True,
                }
            )

        return Response(
            {
                "date": target_date.isoformat(),
                "patient_id": patient.id,
                "patient_name": patient.full_name,
                "checkup": checkup_data,
                "indicators": indicators_data,
                "treatments": treatments_data,
            }
        )

    @extend_schema(
        request=AddByPhoneSerializer,
        responses=DoctorPatientSerializer,
        summary="Telefon orqali bemorga so'rov yuborish",
        description=(
            "Doctor bemor telefon raqamini kiritadi. Patient tomonida pending so'rov "
            "ko'rinadi — patient accept/decline qiladi. Self-add (doctor o'zini "
            "o'ziga) — avtomatik accepted (bir user ham doctor, ham patient "
            "bo'la oladi)."
        ),
    )
    @action(detail=False, methods=["post"], url_path="me/add-patient")
    def add_patient(self, request):
        serializer = AddByPhoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        patient = User.objects.get(phone=serializer.validated_data["phone"])
        self_add = patient == request.user

        profile, _ = DoctorProfile.objects.get_or_create(user=request.user)

        defaults = {
            "added_by": DoctorPatient.AddedBy.DOCTOR,
            "requested_by": DoctorPatient.AddedBy.DOCTOR,
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
            patient=patient,
            defaults=defaults,
        )

        # Declined bo'lsa qayta pending qilamiz
        re_requested = False
        if not created and dp.status == DoctorPatient.Status.DECLINED:
            dp.status = DoctorPatient.Status.PENDING
            dp.requested_by = DoctorPatient.AddedBy.DOCTOR
            dp.responded_at = None
            dp.save(update_fields=["status", "requested_by", "responded_at"])
            re_requested = True

        # Patient'ga push: doctor sizga bog'lanish so'rovi yubordi.
        # Self-add (auto-accepted) yoki mavjud accepted/pending yozuv uchun push yo'q.
        should_notify = not self_add and (
            (created and dp.status == DoctorPatient.Status.PENDING) or re_requested
        )
        if should_notify:
            try:
                notify_by_key_user.delay(
                    user_id=patient.id,
                    type=Notification.Type.CONNECTION_REQUEST,
                    key="connection_request",
                    params={"name": doctor_display_name(profile.user)},
                    data={
                        "connection_id": str(dp.id),
                        "doctor_id": str(profile.id),
                    },
                    app_scope="patient",
                )
            except Exception:
                pass

        return Response(
            DoctorPatientSerializer(dp).data,
            status=201 if created else 200,
        )

    @extend_schema(
        summary="Mening bog'lanish so'rovlarim (doctor uchun)",
        description="Patient'lardan kelgan pending so'rovlarni qaytaradi.",
    )
    @action(detail=False, methods=["get"], url_path="me/connections/pending")
    def pending_connections(self, request):
        profile = getattr(request.user, "doctor_profile", None)
        if not profile:
            return Response([])
        qs = (
            DoctorPatient.objects.filter(
                doctor=profile,
                status=DoctorPatient.Status.PENDING,
                requested_by=DoctorPatient.AddedBy.PATIENT,
            )
            .select_related("patient")
            .order_by("-created_at")
        )
        return Response(DoctorPatientSerializer(qs, many=True).data)

    def _respond_to_connection(self, connection_id, new_status):
        """Patient'dan kelgan pending so'rovni accept yoki decline qilish."""
        profile = getattr(self.request.user, "doctor_profile", None)
        if not profile:
            return Response({"detail": "Doctor profili yo'q."}, status=400)

        dp = DoctorPatient.objects.filter(
            id=connection_id,
            doctor=profile,
            status=DoctorPatient.Status.PENDING,
            requested_by=DoctorPatient.AddedBy.PATIENT,
        ).first()
        if not dp:
            return Response(
                {"detail": "So'rov topilmadi yoki sizga tegishli emas."},
                status=404,
            )
        dp.status = new_status
        dp.responded_at = timezone.now()
        dp.save(update_fields=["status", "responded_at"])

        # Patient (so'rov egasi) ga push: doctor accept yoki decline qildi
        is_accepted = new_status == DoctorPatient.Status.ACCEPTED
        try:
            notify_by_key_user.delay(
                user_id=dp.patient_id,
                type=(
                    Notification.Type.CONNECTION_ACCEPTED
                    if is_accepted
                    else Notification.Type.CONNECTION_DECLINED
                ),
                key=("connection_accepted" if is_accepted else "connection_declined"),
                params={"name": doctor_display_name(profile.user)},
                data={
                    "connection_id": str(dp.id),
                    "doctor_id": str(profile.id),
                },
                app_scope="patient",
            )
        except Exception:
            pass

        return Response(DoctorPatientSerializer(dp).data)

    @extend_schema(
        summary="Bog'lanish so'rovini qabul qilish (doctor)",
        description="Patient'dan kelgan pending so'rovni accepted qiladi.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=r"me/connections/(?P<connection_id>\d+)/accept",
    )
    def accept_connection(self, request, connection_id=None):
        return self._respond_to_connection(
            connection_id, DoctorPatient.Status.ACCEPTED
        )

    @extend_schema(
        summary="Bog'lanish so'rovini rad etish (doctor)",
        description="Patient'dan kelgan pending so'rovni declined qiladi.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path=r"me/connections/(?P<connection_id>\d+)/decline",
    )
    def decline_connection(self, request, connection_id=None):
        return self._respond_to_connection(
            connection_id, DoctorPatient.Status.DECLINED
        )

    @extend_schema(
        summary="Bemorni ro'yxatdan olib tashlash (disconnect)",
        description="Doctor o'z bemorlar ro'yxatidan disconnect qiladi. Faqat o'z bog'lanishini uza oladi.",
        parameters=[
            OpenApiParameter(
                name="patient_id",
                type=int,
                location=OpenApiParameter.PATH,
                required=True,
                description="Bemor user ID si",
            )
        ],
    )
    @action(
        detail=False,
        methods=["delete"],
        url_path=r"me/patients/(?P<patient_id>\d+)/disconnect",
    )
    def disconnect_patient(self, request, patient_id=None):
        profile = getattr(request.user, "doctor_profile", None)
        if not profile:
            return Response({"detail": "Doctor profili topilmadi."}, status=400)

        # 1. DoctorPatient yozuvlarini o'chirish
        dp_deleted, _ = DoctorPatient.objects.filter(
            doctor=profile, patient_id=patient_id
        ).delete()

        # 2. Referral link'ni tozalash (patient QR orqali shu doctor'ga bog'langan bo'lsa)
        referral_cleared = (
            User.objects.filter(id=patient_id, referred_by=request.user).update(
                referred_by=None
            )
            > 0
        )

        if not dp_deleted and not referral_cleared:
            return Response(
                {"detail": "Bu bemor sizning ro'yxatingizda yo'q."}, status=404
            )

        return Response(status=204)

    @extend_schema(
        request=inline_serializer(
            name="DoctorVerifyRequest",
            fields={"is_verified": drf_serializers.BooleanField()},
        ),
        responses=DoctorProfileSerializer,
        summary="Doctor verifyatsiyasini boshqarish (Super Admin)",
        description=(
            "Body'da `is_verified: true|false` aniq ko'rsatilishi shart. "
            "Toggle xavfli bo'lgani uchun explicit qiymat majburiy."
        ),
        tags=["Admin - Verify Doctor"],
    )
    @action(detail=True, methods=["patch"], url_path="verify")
    def verify(self, request, pk=None):
        profile = self.get_object()
        is_verified = request.data.get("is_verified")
        if is_verified is None:
            return Response(
                {"detail": "is_verified majburiy (true yoki false)."},
                status=400,
            )
        profile.is_verified = bool(is_verified)
        profile.save(update_fields=["is_verified"])
        return Response(DoctorProfileSerializer(profile).data)

    @extend_schema(
        summary="Doctor individual komissiyasini belgilash (Super Admin)",
        description=(
            "Body: {\"commission_percent\": 12.5} — individual foiz; null yuborilsa "
            "global SystemSetting[doctor_commission_percent]'ga qaytadi."
        ),
        tags=["Admin - Verify Doctor"],
    )
    @action(detail=True, methods=["patch"], url_path="commission")
    def commission(self, request, pk=None):
        profile = self.get_object()
        if "commission_percent" not in request.data:
            return Response(
                {"detail": "commission_percent majburiy (son yoki null)."},
                status=400,
            )
        value = request.data.get("commission_percent")
        if value is not None:
            try:
                value = Decimal(str(value))
            except (InvalidOperation, TypeError):
                return Response(
                    {"detail": "commission_percent noto'g'ri son."}, status=400
                )
            if not (Decimal("0") <= value <= Decimal("100")):
                return Response(
                    {"detail": "commission_percent 0..100 oralig'ida bo'lsin."},
                    status=400,
                )
        profile.commission_percent = value  # None -> global'ga qaytadi
        profile.save(update_fields=["commission_percent"])
        return Response(DoctorProfileSerializer(profile).data)

    @extend_schema(
        summary="Konsultatsiya moderatsiya navbati (Admin)",
        description=(
            "consultation_enabled=True doctorlar (pullik video-konsultatsiya yoqganlar). "
            "`?status=pending|approved|rejected` filtri ixtiyoriy; berilmasa "
            "hammasi. Sahifalangan — `page_size` qo'llab-quvvatlanadi. Admin panel bu "
            "ro'yxatdan pending'larni tasdiqlaydi/rad etadi (tariff moderatsiyasi kabi)."
        ),
        tags=["Admin - Verify Doctor"],
    )
    @action(detail=False, methods=["get"], url_path="consultations")
    def consultation_queue(self, request):
        qs = self.get_queryset().filter(consultation_enabled=True)
        status_f = (request.query_params.get("status") or "").strip()
        valid = {c for c, _ in DoctorProfile.ConsultationStatus.choices}
        if status_f in valid:
            qs = qs.filter(consultation_status=status_f)
        # Yangi o'zgarganlar tepada (moderatsiya navbati).
        qs = qs.order_by("-id")
        page = self.paginate_queryset(qs)
        target = page if page is not None else qs
        serializer = DoctorProfileSerializer(
            target, many=True, context={"request": request}
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        summary="Konsultatsiyani tasdiqlash (moderatsiya)",
        tags=["Admin - Verify Doctor"],
    )
    @action(detail=True, methods=["post"], url_path="consultation/approve")
    def consultation_approve(self, request, pk=None):
        profile = self.get_object()
        profile.consultation_status = DoctorProfile.ConsultationStatus.APPROVED
        profile.consultation_rejection_reason = ""
        profile.save(
            update_fields=["consultation_status", "consultation_rejection_reason"]
        )
        self._notify_consultation_moderation(profile, approved=True)
        return Response(
            DoctorProfileSerializer(profile, context={"request": request}).data
        )

    @extend_schema(
        summary="Konsultatsiyani rad etish (moderatsiya). Body: {reason}",
        tags=["Admin - Verify Doctor"],
    )
    @action(detail=True, methods=["post"], url_path="consultation/reject")
    def consultation_reject(self, request, pk=None):
        profile = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "reason majburiy."}, status=400)
        profile.consultation_status = DoctorProfile.ConsultationStatus.REJECTED
        profile.consultation_rejection_reason = reason
        profile.save(
            update_fields=["consultation_status", "consultation_rejection_reason"]
        )
        self._notify_consultation_moderation(profile, approved=False, reason=reason)
        return Response(
            DoctorProfileSerializer(profile, context={"request": request}).data
        )

    def _notify_consultation_moderation(self, profile, approved, reason=None):
        """Doctorga konsultatsiya moderatsiya natijasi push (best-effort, app_scope=doctor)."""
        from app.notifications.models import Notification
        from app.notifications.tasks import notify_user

        try:
            if approved:
                notify_user.delay(
                    user_id=profile.user_id,
                    type=Notification.Type.CONSULTATION_APPROVED,
                    title="Konsultatsiya tasdiqlandi",
                    body="Konsultatsiya xizmatingiz moderatsiyadan o'tdi — endi bemorlarga ko'rinadi.",
                    data={"doctor_id": str(profile.id)},
                    app_scope="doctor",
                )
            else:
                notify_user.delay(
                    user_id=profile.user_id,
                    type=Notification.Type.CONSULTATION_REJECTED,
                    title="Konsultatsiya rad etildi",
                    body=f"Konsultatsiya xizmatingiz rad etildi. Sabab: {reason}",
                    data={"doctor_id": str(profile.id)},
                    app_scope="doctor",
                )
        except Exception:
            pass  # push best-effort — moderatsiya natijasi baribir saqlangan

    def get_permissions(self):
        if self.action in ("list", "retrieve", "marketplace"):
            return [IsAuthenticated()]
        # O'z profilini ko'rish/tahrirlash — tasdiqlanmagan doctor ham (profil
        # to'ldirish + verification holatini bilish uchun). is_verified TEKSHIRILMAYDI.
        if self.action == "me":
            return [IsDoctor()]
        # Bemor bilan ishlash (operatsion) — faqat tasdiqlangan doctor.
        if self.action in (
            "my_patients",
            "add_patient",
            "patient_detail",
            "disconnect_patient",
            "daily_report",
            "pending_connections",
            "accept_connection",
            "decline_connection",
        ):
            return [IsVerifiedDoctor()]
        if self.action in ("verify", "commission"):
            return [IsSuperAdmin()]
        return [IsSuperOrSimpleAdmin()]


