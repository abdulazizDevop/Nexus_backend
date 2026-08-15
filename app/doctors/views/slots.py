from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar + helperlar


def _slot_minutes(start, end):
    """start..end orasidagi minutlar (sutka chegarasidan o'tmaydi)."""
    return (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)


def _validate_slot_times(date_, start, end):
    """Yagona slot uchun vaqt qoidalari. Xatolik error_key qaytaradi yoki None."""
    today = timezone.localdate()
    if date_ < today:
        return ("errors.slot_past_date", "O'tgan sanaga slot qo'shib bo'lmaydi.")
    if date_ > today + timedelta(days=SLOT_WINDOW_DAYS):
        return (
            "errors.slot_past_date",
            f"Slot {SLOT_WINDOW_DAYS} kundan keyin bo'lishi mumkin emas.",
        )
    if start >= end:
        return (
            "errors.slot_invalid_range",
            "Boshlanish vaqti tugash vaqtidan kichik bo'lishi kerak.",
        )
    minutes = _slot_minutes(start, end)
    if minutes < SLOT_MIN_MINUTES:
        return ("errors.slot_too_short", "Slot 5 daqiqadan kam bo'lmasligi kerak.")
    if minutes > SLOT_MAX_MINUTES:
        return ("errors.slot_too_long", "Slot 4 soatdan ko'p bo'lmasligi kerak.")
    return None


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


class _BatchValidationError(Exception):
    """Atomic transaction ichida rollback uchun ishlatiladi."""


@extend_schema(tags=["Doctor - Slotlar"])
class DoctorMeSlotsView(APIView):
    """`GET /api/v1/doctors/me/slots/` — bugundan +90 kungacha slotlar."""

    permission_classes = [IsVerifiedDoctor]

    @extend_schema(
        summary="O'z slotlarim (next 90 days)",
        description=(
            "Bugundan boshlab kelajakdagi 90 kungacha barcha statusdagi "
            "(free/booked/blocked) slotlar. Sortlash: date ASC, start_time ASC."
        ),
        responses=inline_serializer(
            name="SlotsListResponse",
            fields={"slots": SlotSerializer(many=True)},
        ),
    )
    def get(self, request):
        profile = getattr(request.user, "doctor_profile", None)
        if not profile:
            return Response({"slots": []})

        today = timezone.localdate()
        upper = today + timedelta(days=SLOT_WINDOW_DAYS)
        qs = Slot.objects.filter(
            doctor=profile, date__gte=today, date__lte=upper
        ).order_by("date", "start_time")

        return Response({"slots": SlotSerializer(qs, many=True).data})


@extend_schema(tags=["Doctor - Slotlar"])
class DoctorMeSlotsSyncView(APIView):
    """`POST /api/v1/doctors/me/slots/sync/` — atomic batch save."""

    permission_classes = [IsVerifiedDoctor]

    @extend_schema(
        request=SlotSyncRequestSerializer,
        responses=inline_serializer(
            name="SlotSyncResponse",
            fields={
                "created": SlotSerializer(many=True),
                "updated": SlotSerializer(many=True),
                "deleted": drf_serializers.ListField(child=drf_serializers.IntegerField()),
            },
        ),
        summary="Batch save (create + update + delete)",
        description=(
            "Atomic transaction. Bitta operatsiya muvaffaqiyatsiz bo'lsa — hammasi rollback. "
            "Tartib: DELETE → UPDATE → CREATE."
        ),
    )
    def post(self, request):
        profile, _ = DoctorProfile.objects.get_or_create(user=request.user)

        serializer = SlotSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        creates = list(payload.get("create") or [])
        updates = list(payload.get("update") or [])
        deletes = list(payload.get("delete") or [])

        errors = []

        # 1) Format-level validation (DB'ga tegmasdan)
        create_plans = []  # (idx, date, start, end, status, reason)
        for idx, item in enumerate(creates):
            date_ = item["date"]
            start = item["start_time"]
            end = item["end_time"]
            status_ = item.get("status") or Slot.Status.FREE
            reason = (item.get("reason") or "").strip()

            payload_repr = {
                "date": date_.isoformat(),
                "start_time": start.strftime("%H:%M"),
                "end_time": end.strftime("%H:%M"),
            }

            if status_ not in (Slot.Status.FREE, Slot.Status.BLOCKED):
                errors.append(
                    {
                        "operation": "create",
                        "index": idx,
                        "payload": payload_repr,
                        "error_key": "errors.slot_has_booking",
                    }
                )
                continue

            if status_ == Slot.Status.BLOCKED and not reason:
                errors.append(
                    {
                        "operation": "create",
                        "index": idx,
                        "payload": payload_repr,
                        "error_key": "errors.blocked_reason_required",
                    }
                )
                continue

            if status_ == Slot.Status.FREE:
                reason = ""

            err = _validate_slot_times(date_, start, end)
            if err:
                errors.append(
                    {
                        "operation": "create",
                        "index": idx,
                        "payload": payload_repr,
                        "error_key": err[0],
                    }
                )
                continue

            create_plans.append((idx, date_, start, end, status_, reason))

        # update_plans dast­labki bosqichda (DB'siz) format tekshiruvidan o'tadi
        update_plans = []  # (idx, item_id, new_start, new_end, new_status, new_reason)
        for idx, item in enumerate(updates):
            sid = item["id"]
            new_status = item.get("status")
            new_reason = item.get("reason")

            if new_status is not None and new_status not in (
                Slot.Status.FREE,
                Slot.Status.BLOCKED,
            ):
                errors.append(
                    {
                        "operation": "update",
                        "index": idx,
                        "id": sid,
                        "error_key": "errors.slot_has_booking",
                    }
                )
                continue

            update_plans.append(
                (
                    idx,
                    sid,
                    item.get("start_time"),
                    item.get("end_time"),
                    new_status,
                    new_reason,
                )
            )

        if errors:
            return Response(
                {"detail": "errors.batch_failed", "errors": errors}, status=409
            )

        # 2) Atomic transaction: lock + DB-level validation + apply
        try:
            with transaction.atomic():
                update_ids = [p[1] for p in update_plans]
                delete_ids = list(set(deletes))

                # Doctor filtr SIZ — keyin ownership tekshiramiz (forbidden vs not_found)
                update_map_all = {
                    s.id: s
                    for s in Slot.objects.select_for_update().filter(id__in=update_ids)
                }
                delete_map_all = {
                    s.id: s
                    for s in Slot.objects.select_for_update().filter(id__in=delete_ids)
                }
                update_map = {
                    sid: s for sid, s in update_map_all.items() if s.doctor_id == profile.id
                }
                delete_map = {
                    sid: s for sid, s in delete_map_all.items() if s.doctor_id == profile.id
                }

                # DELETE preflight
                for sid in delete_ids:
                    slot = delete_map_all.get(sid)
                    if not slot:
                        errors.append(
                            {
                                "operation": "delete",
                                "id": sid,
                                "error_key": "errors.not_found",
                            }
                        )
                        continue
                    if slot.doctor_id != profile.id:
                        errors.append(
                            {
                                "operation": "delete",
                                "id": sid,
                                "error_key": "errors.forbidden",
                            }
                        )
                        continue
                    if slot.status == Slot.Status.BOOKED:
                        errors.append(
                            {
                                "operation": "delete",
                                "id": sid,
                                "error_key": "errors.slot_has_booking",
                            }
                        )

                # UPDATE preflight (yangi qiymatlarni hisoblash)
                update_resolved = []  # (idx, slot_obj, new_start, new_end, new_status, new_reason)
                for idx, sid, ns, ne, nstatus, nreason in update_plans:
                    slot = update_map_all.get(sid)
                    if not slot:
                        errors.append(
                            {
                                "operation": "update",
                                "index": idx,
                                "id": sid,
                                "error_key": "errors.not_found",
                            }
                        )
                        continue
                    if slot.doctor_id != profile.id:
                        errors.append(
                            {
                                "operation": "update",
                                "index": idx,
                                "id": sid,
                                "error_key": "errors.forbidden",
                            }
                        )
                        continue
                    if slot.status == Slot.Status.BOOKED:
                        errors.append(
                            {
                                "operation": "update",
                                "index": idx,
                                "id": sid,
                                "error_key": "errors.slot_has_booking",
                            }
                        )
                        continue

                    new_start = ns or slot.start_time
                    new_end = ne or slot.end_time
                    new_status = nstatus or slot.status
                    new_reason = slot.reason if nreason is None else nreason.strip()

                    if new_status == Slot.Status.BLOCKED and not new_reason:
                        errors.append(
                            {
                                "operation": "update",
                                "index": idx,
                                "id": sid,
                                "error_key": "errors.blocked_reason_required",
                            }
                        )
                        continue

                    if new_status == Slot.Status.FREE:
                        new_reason = ""

                    err = _validate_slot_times(slot.date, new_start, new_end)
                    if err:
                        errors.append(
                            {
                                "operation": "update",
                                "index": idx,
                                "id": sid,
                                "error_key": err[0],
                            }
                        )
                        continue

                    update_resolved.append(
                        (idx, slot, new_start, new_end, new_status, new_reason)
                    )

                if errors:
                    raise _BatchValidationError()

                # Affected dates — overlap tekshiruv uchun
                affected_dates = {p[1] for p in create_plans}
                for _, slot, _, _, _, _ in update_resolved:
                    affected_dates.add(slot.date)

                # Affected sanalardagi barcha mavjud slotlar (lock bilan)
                existing_locked = list(
                    Slot.objects.select_for_update().filter(
                        doctor=profile, date__in=affected_dates
                    )
                )

                # Final intervals per date — overlap detektor uchun
                modified_ids = set(update_map.keys()) | set(delete_map.keys())
                final_by_date = {}
                for s in existing_locked:
                    if s.id in modified_ids:
                        continue
                    final_by_date.setdefault(s.date, []).append(
                        (s.start_time, s.end_time, ("keep", s.id))
                    )
                for _, slot, new_start, new_end, _, _ in update_resolved:
                    final_by_date.setdefault(slot.date, []).append(
                        (new_start, new_end, ("update", slot.id))
                    )
                for idx, date_, start, end, _, _ in create_plans:
                    final_by_date.setdefault(date_, []).append(
                        (start, end, ("create", idx))
                    )

                # Pairwise overlap tekshiruvi (sana ichida)
                for date_, intervals in final_by_date.items():
                    intervals.sort(key=lambda t: t[0])
                    for i in range(len(intervals) - 1):
                        a_start, a_end, a_label = intervals[i]
                        b_start, b_end, b_label = intervals[i + 1]
                        if _intervals_overlap(a_start, a_end, b_start, b_end):
                            op, identifier = b_label
                            both_in_batch = op in ("create", "update") and a_label[
                                0
                            ] in ("create", "update")
                            err_key = (
                                "errors.slot_overlap_in_batch"
                                if both_in_batch
                                else "errors.slot_overlap"
                            )
                            entry = {
                                "operation": op,
                                "error_key": err_key,
                                "payload": {
                                    "date": date_.isoformat(),
                                    "start_time": b_start.strftime("%H:%M"),
                                    "end_time": b_end.strftime("%H:%M"),
                                },
                            }
                            if op == "create":
                                entry["index"] = identifier
                            else:
                                entry["id"] = identifier
                            if a_label[0] == "keep":
                                entry["conflict_with_id"] = a_label[1]
                            elif a_label[0] in ("update", "create"):
                                entry["conflict_with"] = {
                                    "operation": a_label[0],
                                    ("id" if a_label[0] == "update" else "index"): a_label[1],
                                }
                            errors.append(entry)

                if errors:
                    raise _BatchValidationError()

                # Apply: DELETE → UPDATE → CREATE
                deleted_ids = []
                if delete_map:
                    Slot.objects.filter(id__in=list(delete_map.keys())).delete()
                    deleted_ids = list(delete_map.keys())

                updated_objs = []
                for _, slot, new_start, new_end, new_status, new_reason in update_resolved:
                    slot.start_time = new_start
                    slot.end_time = new_end
                    slot.status = new_status
                    slot.reason = new_reason
                    slot.save(
                        update_fields=[
                            "start_time",
                            "end_time",
                            "status",
                            "reason",
                            "updated_at",
                        ]
                    )
                    updated_objs.append(slot)

                created_objs = []
                for _, date_, start, end, status_, reason in create_plans:
                    obj = Slot.objects.create(
                        doctor=profile,
                        date=date_,
                        start_time=start,
                        end_time=end,
                        status=status_,
                        reason=reason,
                    )
                    created_objs.append(obj)
        except _BatchValidationError:
            return Response(
                {"detail": "errors.batch_failed", "errors": errors}, status=409
            )
        except IntegrityError:
            # Pre-flight overlap check'ni o'tib ketgan kamdan-kam holat:
            # konkurent so'rov yoki unique constraint buzilishi (uniq_slot_doctor_date_start).
            return Response(
                {
                    "detail": "errors.batch_failed",
                    "errors": [
                        {
                            "error_key": "errors.slot_overlap",
                            "message": (
                                "Slot konflikti — boshqa request bir vaqtda saqladi. "
                                "Iltimos, qaytadan urinib ko'ring."
                            ),
                        }
                    ],
                },
                status=409,
            )

        return Response(
            {
                "created": SlotSerializer(created_objs, many=True).data,
                "updated": SlotSerializer(updated_objs, many=True).data,
                "deleted": deleted_ids,
            }
        )


def _parse_date_param(request):
    """`?date=YYYY-MM-DD` query param'ni parse qiladi.

    Returns: (date, error_response). Bittasi None.
    """
    date_str = request.query_params.get("date")
    if not date_str:
        return None, Response(
            {"detail": "date parametri kerak (?date=YYYY-MM-DD)."}, status=400
        )
    try:
        return dt.strptime(date_str, "%Y-%m-%d").date(), None
    except ValueError:
        return None, Response(
            {"detail": "Sana formati noto'g'ri. YYYY-MM-DD."}, status=400
        )


@extend_schema(tags=["Admin - Doctor Slotlar"])
class AdminDoctorSlotsView(APIView):
    """`GET /api/v1/admin/doctors/{doctor_id}/slots/?date=YYYY-MM-DD` — admin uchun.

    Patient public endpoint'idan farqi: barcha statusdagi (free/booked/blocked)
    slotlar qaytariladi va booked bo'lsa appointment ma'lumotlari nested.
    """

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        summary="Admin: doctor uchun barcha slotlar (sana bo'yicha)",
        description=(
            "Admin panel uchun. Booked slotlarda appointment ma'lumotlari (status, "
            "patient ismi, meeting_type) nested. Patient public endpoint faqat free "
            "slotlarni qaytaradi."
        ),
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="YYYY-MM-DD",
            )
        ],
        responses=inline_serializer(
            name="AdminDoctorSlotsResponse",
            fields={"slots": AdminSlotSerializer(many=True)},
        ),
    )
    def get(self, request, doctor_id=None):
        target, err = _parse_date_param(request)
        if err:
            return err

        try:
            doctor = DoctorProfile.objects.get(pk=doctor_id, is_deleted=False)
        except DoctorProfile.DoesNotExist:
            return Response({"detail": "Doctor topilmadi."}, status=404)

        qs = (
            Slot.objects.filter(doctor=doctor, date=target)
            .select_related("appointment__patient")
            .order_by("start_time")
        )
        return Response({"slots": AdminSlotSerializer(qs, many=True).data})


@extend_schema(tags=["Doctor - Slotlar"])
class PublicDoctorSlotsView(APIView):
    """`GET /api/v1/doctors/{doctor_id}/slots/?date=YYYY-MM-DD` — bemor uchun bo'sh slotlar."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Berilgan doctor uchun bo'sh slotlar (sana bo'yicha)",
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="YYYY-MM-DD",
            )
        ],
        responses=inline_serializer(
            name="PublicSlotsListResponse",
            fields={"slots": SlotSerializer(many=True)},
        ),
    )
    def get(self, request, doctor_id=None):
        target, err = _parse_date_param(request)
        if err:
            return err

        try:
            doctor = DoctorProfile.objects.get(
                pk=doctor_id, user__is_active=True, is_deleted=False
            )
        except DoctorProfile.DoesNotExist:
            return Response({"detail": "Doctor topilmadi."}, status=404)

        # TIME_ZONE muhim: localtime (Asia/Tashkent) ishlatamiz, slot.start_time
        # DB'da naive — Asia/Tashkent vaqtida saqlanadi. timezone.now() UTC qaytaradi
        # va 5 soat farq tushadi → bugungi slotlar noto'g'ri filter qilinadi.
        now = timezone.localtime()
        if target < now.date():
            return Response({"slots": []})

        qs = Slot.objects.filter(
            doctor=doctor, date=target, status=Slot.Status.FREE
        )
        if target == now.date():
            qs = qs.filter(start_time__gt=now.time())

        return Response({"slots": SlotSerializer(qs.order_by("start_time"), many=True).data})
