from .common import *  # noqa: F401,F403 - umumiy importlar + helperlar

# Audit H8 — har bemorga sutkalik upload-URL chegarasi.
# 5 ta URL × ~10 marta yuklash = 50 ta fayl/sutka — tibbiy holat uchun yetarli.
# (Split'da catalog.py'da qolib ketgan edi — underscore `import *` bermaydi → NameError.)
_DAILY_UPLOAD_URL_LIMIT = 50


@extend_schema(tags=["Medical - Analizlar"])
class AnalysisViewSet(viewsets.ModelViewSet):
    """Analiz tayinlash, ko'rib chiqish, topshirish.

    Doctor:
      - POST   /medical/analyses/                       — tayinlash
      - GET    /medical/analyses/?patient_id=&status=   — bemor analizlari
      - GET    /medical/analyses/{id}/                  — detail
      - PATCH  /medical/analyses/{id}/                  — tahrirlash (prescribed bo'lsa)
      - POST   /medical/analyses/{id}/cancel/           — bekor qilish
      - POST   /medical/analyses/{id}/review/           — natija + verdict

    Patient:
      - GET    /medical/analyses/my/                    — o'z analizlari
      - GET    /medical/analyses/my-upcoming/           — eng yaqin deadline (banner)
      - POST   /medical/analyses/{id}/result-upload-url/ — S3 presigned URL
      - POST   /medical/analyses/{id}/submit/           — natija yuklash
      - POST   /medical/analyses/{id}/cancel/           — bekor qilish
    """

    queryset = Analysis.objects.none()
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head"]

    def get_serializer_class(self):
        if not hasattr(self.request, "user") or not self.request.user.is_authenticated:
            return AnalysisListSerializer
        if self.action in ("list", "my", "my_upcoming"):
            return AnalysisListSerializer
        if self.action == "create":
            return AnalysisCreateSerializer
        if self.action == "partial_update":
            return AnalysisUpdateSerializer
        if self.action == "cancel":
            return AnalysisCancelSerializer
        if self.action == "review":
            return AnalysisReviewSerializer
        if self.action == "submit":
            return AnalysisSubmitSerializer
        if self.action == "result_upload_url":
            return AnalysisResultUploadUrlRequestSerializer
        if self.action == "upload_url":
            return PatientAnalysisUploadUrlRequestSerializer
        if self.action == "upload":
            return PatientAnalysisCreateSerializer
        return AnalysisDetailSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Analysis.objects.none()
        request = self.request
        user = request.user
        if not user or not user.is_authenticated:
            return Analysis.objects.none()
        role = get_request_role(request)
        base = Analysis.objects.select_related(
            "type", "doctor", "patient"
        ).prefetch_related(
            "indicators",
            "preparations",
            "files",
            "recipients__user",
            "recipients__specialty",
            "result__values__indicator",
        )

        # Patient endpoint'lari (my, my-upcoming) — faqat o'z
        if self.action in ("my", "my_upcoming"):
            return base.filter(patient=user)

        if role == "doctor":
            profile = getattr(user, "doctor_profile", None)
            if not profile:
                return base.none()

            patient_ids = list(accepted_patient_ids(profile))
            # Doctor o'z connected bemorlarini ko'radi YOKI patient_uploaded analizlar
            # ichida o'zi recipient bo'lganlarini
            qs = base.filter(
                Q(patient_id__in=patient_ids) | Q(recipients=profile)
            ).distinct()

            if self.action == "list":
                patient_id = request.query_params.get("patient_id")
                if patient_id:
                    qs = qs.filter(patient_id=patient_id)
                status_filter = request.query_params.get("status")
                if status_filter:
                    qs = qs.filter(status=status_filter)
                category = request.query_params.get("category")
                if category:
                    qs = qs.filter(type__category=category)
            return qs

        # Patient — o'z analizlari
        qs = base.filter(patient=user)
        if self.action == "list":
            status_filter = request.query_params.get("status")
            if status_filter:
                qs = qs.filter(status=status_filter)
            category = request.query_params.get("category")
            if category:
                qs = qs.filter(type__category=category)
        return qs

    @extend_schema(
        summary="Bemor analizlari (doctor)",
        parameters=[
            OpenApiParameter("patient_id", int, description="Bemor ID"),
            OpenApiParameter(
                "status",
                str,
                description="prescribed | submitted | reviewed | cancelled",
            ),
            OpenApiParameter(
                "category",
                str,
                description=(
                    "AnalysisType.category bo'yicha: "
                    "blood | urine | imaging | cardiac | hormones | infection | other"
                ),
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Analiz tayinlash (doctor)")
    def create(self, request, *args, **kwargs):
        role = get_request_role(request)
        if role != "doctor":
            return Response(
                {"detail": "Faqat shifokor analiz tayinlay oladi."}, status=403
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        patient_id = data.pop("patient_id")

        if not doctor_can_access_patient(request.user, patient_id):
            return Response(
                {"detail": "Bemor topilmadi yoki ruxsat yo'q."}, status=404
            )

        indicators = data.pop("indicators", [])
        preparations = data.pop("preparations", [])

        analysis = Analysis.objects.create(
            patient_id=patient_id,
            doctor=request.user,
            **data,
        )
        if indicators:
            analysis.indicators.set(indicators)
        if preparations:
            analysis.preparations.set(preparations)

        # Push bemorga (FAZA D — catalog'dan til bo'yicha)
        try:

            type_name = analysis.type_name_for(analysis.patient)
            deadline_date = analysis.deadline_at.strftime("%d-%b")
            notify_by_key(
                analysis.patient,
                type=Notification.Type.SYSTEM,
                key="analysis_assigned",
                params={"type_name": type_name, "deadline": deadline_date},
                data={
                    "kind": "analysis_prescribed",
                    "analysis_id": str(analysis.id),
                },
                app_scope="patient",
            )
        except Exception:
            pass

        return Response(
            AnalysisDetailSerializer(analysis).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(summary="Analiz detail", responses=AnalysisDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Analiz tahrirlash (doctor, faqat prescribed)")
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        role = get_request_role(request)
        if role != "doctor" or instance.doctor_id != request.user.id:
            return Response(
                {"detail": "Faqat tayinlagan shifokor tahrirlay oladi."}, status=403
            )
        if instance.status != Analysis.Status.PRESCRIBED:
            return Response(
                {"detail": "Faqat 'prescribed' statusdagi analizni tahrirlash mumkin."},
                status=400,
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        instance.refresh_from_db()
        return Response(AnalysisDetailSerializer(instance).data)

    @extend_schema(exclude=True)
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    # ---------- Patient endpointlari ----------

    @extend_schema(
        summary="O'zimning analizlarim (patient)",
        parameters=[
            OpenApiParameter(
                "status",
                str,
                description="prescribed | submitted | reviewed | cancelled | private",
            ),
            OpenApiParameter(
                "source",
                str,
                description="doctor_prescribed | patient_uploaded",
            ),
            OpenApiParameter("type_id", int, description="AnalysisType ID filter"),
            OpenApiParameter(
                "category",
                str,
                description=(
                    "AnalysisType.category bo'yicha guruh: "
                    "blood | urine | imaging | cardiac | hormones | infection | other. "
                    "Frontend tab uchun (Qon / Siydik / Tasvir / ...)."
                ),
            ),
            OpenApiParameter(
                "ui_status",
                str,
                description=(
                    "Frontend badge: "
                    "sent (YUBORILDI — doctor hali ko'rmagan) | "
                    "viewed (KO'RILDI — doctor ko'rdi, sharh yo'q) | "
                    "commented (SHARH KELDI — doctor sharh yozdi) | "
                    "prescribed | cancelled"
                ),
            ),
            OpenApiParameter(
                "q", str, description="Title yoki type.name bo'yicha qidirish"
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="my")
    def my(self, request):
        if get_request_role(request) != "patient":
            return Response(
                {"detail": "Faqat bemor o'z analizlarini ko'ra oladi."}, status=403
            )

        qs = self.get_queryset()

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        source_filter = request.query_params.get("source")
        if source_filter:
            qs = qs.filter(source=source_filter)
        type_id = request.query_params.get("type_id")
        if type_id:
            qs = qs.filter(type_id=type_id)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(type__category=category)
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(type__name__icontains=q))

        # ui_status filter — derived, shuning uchun DB filter o'rniga mapping kerak.
        # Mapping serializers.ui_status_q'da (_compute_ui_status bilan bir joyda).
        ui_status = request.query_params.get("ui_status")
        if ui_status:
            from ..serializers import ui_status_q

            ui_q = ui_status_q(ui_status)
            if ui_q is not None:
                qs = qs.filter(ui_q)

        page = self.paginate_queryset(qs)
        ser = AnalysisListSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(ser.data)
        return Response(ser.data)

    @extend_schema(
        summary="Eng yaqin tayinlangan analiz (patient — banner)",
        description=(
            "Home banner uchun: prescribed status'dagi va deadline'ga eng yaqin "
            "analiz. Hech narsa bo'lmasa null qaytaradi."
        ),
    )
    @action(detail=False, methods=["get"], url_path="my-upcoming")
    def my_upcoming(self, request):
        if get_request_role(request) != "patient":
            return Response(
                {"detail": "Faqat bemor o'z analizlarini ko'ra oladi."}, status=403
            )

        pending = (
            self.get_queryset()
            .filter(
                status=Analysis.Status.PRESCRIBED,
                deadline_at__gte=timezone.now(),
            )
            .order_by("deadline_at")
        )
        total_pending = pending.count()
        nearest = pending.first()
        return Response(
            {
                "total_pending": total_pending,
                "nearest": AnalysisListSerializer(nearest).data if nearest else None,
            }
        )

    @extend_schema(
        summary="Natija yuklash uchun S3 presigned URL (patient)",
        request=AnalysisResultUploadUrlRequestSerializer,
        responses=AnalysisResultUploadUrlResponseSerializer,
        description=(
            "Mobile flow: "
            "1) Bu endpoint dan upload_url + file_key olinadi, "
            "2) PUT {upload_url} bilan fayl DO Spaces ga yuklanadi (15 daqiqa), "
            "3) POST /medical/analyses/{id}/submit/ {file_key, values} bilan tasdiqlanadi."
        ),
    )
    @action(detail=True, methods=["post"], url_path="result-upload-url")
    def result_upload_url(self, request, pk=None):
        analysis = self.get_object()
        if analysis.patient_id != request.user.id:
            return Response(
                {"detail": "Faqat bemor o'zi natija yuklay oladi."}, status=403
            )
        if analysis.status not in (
            Analysis.Status.PRESCRIBED,
            Analysis.Status.SUBMITTED,
        ):
            return Response(
                {"detail": "Bu analiz uchun natija yuklash mumkin emas."}, status=400
            )

        serializer = AnalysisResultUploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_type = serializer.validated_data["file_type"]

        prefix = f"analyses/{analysis.patient_id}/{analysis.id}/"
        return Response(build_upload_item(prefix, file_type, fallback_ext="pdf"))

    @extend_schema(
        summary="Natijani topshirish (patient)",
        request=AnalysisSubmitSerializer,
        responses=AnalysisDetailSerializer,
    )
    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):

        analysis = self.get_object()
        if analysis.patient_id != request.user.id:
            return Response(
                {"detail": "Faqat bemor o'zi natija topshira oladi."}, status=403
            )
        if analysis.status not in (
            Analysis.Status.PRESCRIBED,
            Analysis.Status.SUBMITTED,
        ):
            return Response(
                {"detail": "Bu analiz holatida natija topshirish mumkin emas."},
                status=400,
            )

        serializer = AnalysisSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # values ichidagi indicator'lar shu analiz turiga tegishlimi
        values = data.get("values") or []
        if values:
            ind_ids = [v["indicator_id"] for v in values]
            valid_ids = set(
                AnalysisIndicator.objects.filter(
                    id__in=ind_ids, type=analysis.type
                ).values_list("id", flat=True)
            )
            missing = [i for i in ind_ids if i not in valid_ids]
            if missing:
                return Response(
                    {
                        "detail": (
                            "Quyidagi indicator'lar shu analiz turiga mos kelmaydi: "
                            f"{missing}"
                        )
                    },
                    status=400,
                )

        # Fayllar — `files[]` ustun, bo'lmasa eski single `file_key` ishlatamiz
        files_input = data.get("files") or []
        if not files_input and data.get("file_key"):
            files_input = [
                {
                    "file_key": data["file_key"],
                    "file_mime": data.get("file_mime", ""),
                }
            ]

        # XAVFSIZLIK: har file_key bemorning O'Z upload prefiksida bo'lsin — aks
        # holda boshqa bemor faylini (PHI) biriktirib imzolangan URL oldirish
        # mumkin (IDOR). Upload har doim analyses/uploads/{user.id}/ beradi.
        # Bundan tashqari HeadObject bilan real MIME/size'ni S3'dan tekshiramiz
        # (upload() dagi C5 audit kabi) — MIME spoofing (.exe) va hajm cheklovi.
        from services.storage import (
            ALLOWED_UPLOAD_MIMES,
            MAX_UPLOAD_BYTES,
            delete_file,
            head_object_or_none,
        )

        # Ikkalasini ham qabul qilamiz. IDOR himoyasi saqlanadi: yuqorida (submit
        # boshida) analysis.patient_id == request.user.id tekshirilgan, shuning uchun
        # ikkala prefiks ham faqat shu user'ning fayllariga ishora qiladi.
        expected_prefixes = (
            f"analyses/uploads/{request.user.id}/",
            f"analyses/{analysis.patient_id}/{analysis.id}/",
        )

        # Legacy single result.file_key — files[] dan mustaqil berilishi mumkin,
        # shuning uchun alohida prefix tekshiruvi (IDOR himoyasi).
        legacy_key = data.get("file_key")
        if legacy_key and not str(legacy_key).startswith(expected_prefixes):
            return Response({"detail": "Noto'g'ri file_key."}, status=400)

        # Tekshirilgan fayllar: file_key → (real_mime, real_size)
        verified = {}
        for f in files_input:
            k = f.get("file_key")
            if not k:
                continue
            if not str(k).startswith(expected_prefixes):
                return Response({"detail": "Noto'g'ri file_key."}, status=400)
            head = head_object_or_none(k)
            if head is None:
                return Response(
                    {"detail": f"Fayl yuklanmadi yoki topilmadi: {k}"}, status=400
                )
            real_mime = head["content_type"]
            real_size = head["size"]
            if real_mime not in ALLOWED_UPLOAD_MIMES:
                delete_file(k)
                return Response(
                    {"detail": "Faqat PDF/JPEG/PNG/HEIC/WebP fayllar qabul qilinadi."},
                    status=400,
                )
            if real_size <= 0 or real_size > MAX_UPLOAD_BYTES:
                delete_file(k)
                return Response(
                    {"detail": "Fayl o'lchami chegaradan tashqari (max 20 MB)."},
                    status=400,
                )
            verified[k] = (real_mime, real_size)

        with transaction.atomic():
            result, _ = AnalysisResult.objects.get_or_create(analysis=analysis)
            if "file_key" in data:
                result.file_key = data["file_key"] or result.file_key
            if "file_mime" in data:
                result.file_mime = data["file_mime"] or result.file_mime
            if "patient_note" in data:
                result.patient_note = data["patient_note"]
            result.save()

            # Multi-file: berilgan bo'lsa eski fayllarni almashtiramiz.
            # MIME/size HeadObject'dan olingan haqiqiy qiymatlar bilan yoziladi.
            if files_input:
                analysis.files.all().delete()
                for idx, f in enumerate(files_input):
                    real_mime, real_size = verified[f["file_key"]]
                    AnalysisFile.objects.create(
                        analysis=analysis,
                        file_key=f["file_key"],
                        file_mime=real_mime,
                        file_size_bytes=real_size,
                        original_name=f.get("original_name", "") or "",
                        order=idx,
                        uploaded_by=request.user,
                    )

            if values:
                # Replace strategy: avval eski qiymatlarni o'chirib, yangidan yozamiz
                result.values.all().delete()
                for v in values:
                    AnalysisResultValue.objects.create(
                        result=result,
                        indicator_id=v["indicator_id"],
                        value=v["value"],
                    )

            if analysis.status != Analysis.Status.SUBMITTED:
                analysis.status = Analysis.Status.SUBMITTED
            analysis.submitted_at = timezone.now()
            analysis.save(update_fields=["status", "submitted_at", "updated_at"])

        # Doctor'ga push
        try:

            if analysis.doctor_id:

                notify_by_key(
                    analysis.doctor,
                    type=Notification.Type.SYSTEM,
                    key="analysis_submitted",
                    params={
                        "patient_name": request.user.full_name or request.user.phone,
                        "type_name": analysis.type_name_for(analysis.doctor),
                    },
                    data={
                        "kind": "analysis_submitted",
                        "analysis_id": str(analysis.id),
                    },
                    app_scope="doctor",
                )
        except Exception:
            pass

        analysis.refresh_from_db()
        return Response(AnalysisDetailSerializer(analysis).data)

    @extend_schema(
        summary="Analizni bekor qilish (doctor yoki patient)",
        request=AnalysisCancelSerializer,
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):

        analysis = self.get_object()
        role = get_request_role(request)

        # Kim bekor qila oladi: tayinlagan doctor yoki tayinlangan bemor
        is_assigned_doctor = role == "doctor" and analysis.doctor_id == request.user.id
        is_assigned_patient = (
            role == "patient" and analysis.patient_id == request.user.id
        )
        if not (is_assigned_doctor or is_assigned_patient):
            return Response(
                {"detail": "Faqat tayinlagan shifokor yoki bemor bekor qila oladi."},
                status=403,
            )
        if analysis.status in (Analysis.Status.REVIEWED, Analysis.Status.CANCELLED):
            return Response(
                {"detail": "Bu analizni bekor qilib bo'lmaydi (allaqachon yopiq)."},
                status=400,
            )

        ser = AnalysisCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data.get("reason", "") or ""

        analysis.status = Analysis.Status.CANCELLED
        analysis.cancelled_at = timezone.now()
        analysis.cancelled_by = request.user
        analysis.cancelled_reason = reason
        analysis.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by",
                "cancelled_reason",
                "updated_at",
            ]
        )

        # Boshqa tomonga push
        try:


            if is_assigned_doctor and analysis.patient_id:
                notify_by_key(
                    analysis.patient,
                    type=Notification.Type.SYSTEM,
                    key="analysis_cancelled_by_doctor",
                    params={"type_name": analysis.type_name_for(analysis.patient)},
                    data={
                        "kind": "analysis_cancelled",
                        "analysis_id": str(analysis.id),
                    },
                    app_scope="patient",
                )
            if is_assigned_patient and analysis.doctor_id:
                notify_by_key(
                    analysis.doctor,
                    type=Notification.Type.SYSTEM,
                    key="analysis_cancelled_by_patient",
                    params={
                        "patient_name": request.user.full_name or request.user.phone,
                        "type_name": analysis.type_name_for(analysis.doctor),
                    },
                    data={
                        "kind": "analysis_cancelled",
                        "analysis_id": str(analysis.id),
                    },
                    app_scope="doctor",
                )
        except Exception:
            pass

        return Response(AnalysisDetailSerializer(analysis).data)

    @extend_schema(
        summary="Sharh yozish (doctor)",
        request=AnalysisReviewSerializer,
        description=(
            "Doctor analizga sharh yozadi.\n"
            "- doctor_prescribed: faqat tayinlagan doctor (`analysis.doctor`).\n"
            "- patient_uploaded: `recipients` ichidagi har qaysi doctor. Birinchi "
            "sharh yozgan doctor `analysis.doctor` sifatida saqlanadi."
        ),
    )
    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):

        analysis = self.get_object()
        if get_request_role(request) != "doctor":
            return Response(
                {"detail": "Faqat shifokor sharh yoza oladi."}, status=403
            )

        # Kim sharh yoza oladi?
        profile = getattr(request.user, "doctor_profile", None)
        is_assigned = analysis.doctor_id == request.user.id
        is_recipient = (
            analysis.source == Analysis.Source.PATIENT_UPLOADED
            and profile is not None
            and analysis.recipients.filter(id=profile.id).exists()
        )
        if not (is_assigned or is_recipient):
            return Response(
                {"detail": "Bu analizga sharh yozish huquqi yo'q."}, status=403
            )

        if analysis.status not in (
            Analysis.Status.SUBMITTED,
            Analysis.Status.REVIEWED,
        ):
            return Response(
                {"detail": "Sharh faqat yuborilgan analizga yoziladi."},
                status=400,
            )

        ser = AnalysisReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        analysis.verdict = ser.validated_data["verdict"]
        analysis.status = Analysis.Status.REVIEWED
        analysis.reviewed_at = timezone.now()
        # patient_uploaded flow'da birinchi sharh yozgan doctorni saqlaymiz
        if not analysis.doctor_id and is_recipient:
            analysis.doctor = request.user
        analysis.save(
            update_fields=[
                "verdict",
                "status",
                "reviewed_at",
                "doctor",
                "doctor_profile",
                "updated_at",
            ]
        )

        # Bemor'ga push (FAZA D — catalog)
        try:

            verdict_preview = (analysis.verdict or "").strip()
            if len(verdict_preview) > 100:
                verdict_preview = verdict_preview[:97] + "..."
            notify_by_key(
                analysis.patient,
                type=Notification.Type.SYSTEM,
                key="analysis_reviewed",
                params={
                    "type_name": analysis.type_name_for(analysis.patient),
                    "verdict_preview": verdict_preview,
                },
                data={
                    "kind": "analysis_reviewed",
                    "analysis_id": str(analysis.id),
                },
                app_scope="patient",
            )
        except Exception:
            pass

        return Response(AnalysisDetailSerializer(analysis).data)

    # ---------- Patient-initiated upload flow ----------

    @extend_schema(
        summary="Yuklash uchun S3 presigned URL (patient, analiz hali yo'q)",
        request=PatientAnalysisUploadUrlRequestSerializer,
        responses=PatientAnalysisUploadUrlResponseSerializer,
        description=(
            "Patient o'zi tashabbus bilan analiz yuklashdan oldin presigned URL oladi. "
            "Har bir fayl uchun alohida `file_key` qaytariladi. "
            "Keyin POST /medical/analyses/upload/ ga `files[].file_key` yuboriladi."
        ),
    )
    @action(detail=False, methods=["post"], url_path="upload-url")
    def upload_url(self, request):
        if get_request_role(request) != "patient":
            return Response(
                {"detail": "Faqat bemor analiz yukla oladi."}, status=403
            )
        ser = PatientAnalysisUploadUrlRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        file_type = ser.validated_data["file_type"]
        count = ser.validated_data.get("count", 1)

        # Audit H8 — per-user kunlik upload URL chegarasi (DO Spaces bill DoS).
        # Lokal dev'da (DEBUG=True) bypass.
        # TOCTOU oldini olish: avval ATOMIK incr, keyin tekshirish. Limitdan
        # oshsa counter'ni qaytarib (decr) rad etamiz — parallel so'rovlar
        # serial hisoblanadi.
        daily_key = f"upload_url:daily:{request.user.id}"
        if not settings.DEBUG:
            try:
                new_count = cache.incr(daily_key, count)
            except ValueError:
                # Kalit yo'q — TTL bilan yaratamiz va shu so'rov hisoblanadi.
                cache.set(daily_key, count, timeout=86400)
                new_count = count
            if new_count > _DAILY_UPLOAD_URL_LIMIT:
                try:
                    cache.decr(daily_key, count)
                except ValueError:
                    pass
                return Response(
                    {
                        "detail": (
                            f"Kunlik fayl yuklash chegarasi "
                            f"({_DAILY_UPLOAD_URL_LIMIT} ta) oshib ketdi. "
                            "Ertaga urinib ko'ring."
                        )
                    },
                    status=429,
                )

        prefix = f"analyses/uploads/{request.user.id}/"
        items = [
            build_upload_item(prefix, file_type, fallback_ext="bin")
            for _ in range(count)
        ]
        return Response({"items": items})

    @extend_schema(
        summary="Patient o'zi analiz yuklaydi (barcha bog'langan doctorlariga ko'rinadi)",
        request=PatientAnalysisCreateSerializer,
        responses=AnalysisDetailSerializer,
        description=(
            "Flow:\n"
            "1) POST /medical/analyses/upload-url/ — file_key'larni olish\n"
            "2) PUT {upload_url} — har bir faylni S3 ga yuklash\n"
            "3) POST /medical/analyses/upload/ — shu endpoint: analiz yaratish + "
            "fayllarni biriktirish.\n\n"
            "Analiz bemorning DoctorPatient.ACCEPTED bog'lanishidagi barcha "
            "doctorlariga avtomatik ko'rinadi va push xabar yuboriladi. Qabul "
            "qiluvchini tanlash kerak emas."
        ),
    )
    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request):

        if get_request_role(request) != "patient":
            return Response(
                {"detail": "Faqat bemor analiz yukla oladi."}, status=403
            )

        ser = PatientAnalysisCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            analysis_type = AnalysisType.objects.get(id=data["type_id"], is_active=True)
        except AnalysisType.DoesNotExist:
            return Response({"detail": "Noto'g'ri analiz turi."}, status=400)

        from app.doctors.models import DoctorPatient, DoctorProfile

        connected_doctor_ids = list(
            DoctorPatient.objects.filter(
                patient=request.user,
                status=DoctorPatient.Status.ACCEPTED,
                doctor__user__is_active=True,
            ).values_list("doctor_id", flat=True)
        )
        recipients_qs = list(
            DoctorProfile.objects.filter(id__in=connected_doctor_ids)
        )

        files = data.get("files") or []

        # Audit C5 — post-upload verification. Mobile presigned URL bilan
        # `image/jpeg` deb URL oladi, S3'ga `.exe` PUT qilishi mumkin edi.
        # HeadObject orqali real ContentType + Size'ni S3'dagi obyektdan
        # qaytadan tekshiramiz. Mosligi bo'lmasa fayl o'chiriladi va so'rov
        # rad etiladi.
        from services.storage import (
            ALLOWED_UPLOAD_MIMES,
            MAX_UPLOAD_BYTES,
            head_object_or_none,
            delete_file,
        )

        expected_prefix = f"analyses/uploads/{request.user.id}/"
        verified_files = []  # (file_key, real_mime, real_size, original_name)
        for f in files:
            key = f["file_key"]

            # IDOR himoyasi: file_key boshqa user'niki bo'lmasin
            if not key.startswith(expected_prefix):
                return Response(
                    {"detail": "Noto'g'ri file_key."}, status=400
                )

            head = head_object_or_none(key)
            if head is None:
                return Response(
                    {"detail": f"Fayl yuklanmadi yoki topilmadi: {key}"},
                    status=400,
                )

            real_mime = head["content_type"]
            real_size = head["size"]

            if real_mime not in ALLOWED_UPLOAD_MIMES:
                delete_file(key)
                return Response(
                    {
                        "detail": (
                            "Faqat PDF/JPEG/PNG/HEIC/WebP fayllar qabul qilinadi."
                        )
                    },
                    status=400,
                )
            if real_size <= 0 or real_size > MAX_UPLOAD_BYTES:
                delete_file(key)
                return Response(
                    {
                        "detail": (
                            "Fayl o'lchami chegaradan tashqari (max 20 MB)."
                        )
                    },
                    status=400,
                )

            verified_files.append(
                (key, real_mime, real_size, f.get("original_name", "") or "")
            )

        with transaction.atomic():
            analysis = Analysis.objects.create(
                patient=request.user,
                type=analysis_type,
                source=Analysis.Source.PATIENT_UPLOADED,
                title=data.get("title", "") or "",
                recorded_at=data.get("recorded_at"),
                status=Analysis.Status.SUBMITTED,
                submitted_at=timezone.now(),
            )
            if recipients_qs:
                analysis.recipients.set(recipients_qs)

            for idx, (key, real_mime, real_size, orig_name) in enumerate(verified_files):
                AnalysisFile.objects.create(
                    analysis=analysis,
                    file_key=key,
                    file_mime=real_mime,
                    file_size_bytes=real_size,
                    original_name=orig_name,
                    order=idx,
                    uploaded_by=request.user,
                )

            patient_note = data.get("patient_note") or ""
            if patient_note:
                AnalysisResult.objects.create(
                    analysis=analysis, patient_note=patient_note
                )

        if recipients_qs:
            try:

                patient_name = request.user.full_name or request.user.phone
                for dp in recipients_qs:
                    if dp.user_id:
                        notify_by_key(
                            dp.user,
                            type=Notification.Type.SYSTEM,
                            key="analysis_received",
                            params={
                                "patient_name": patient_name,
                                "type_name": analysis.type_name_for(dp.user),
                            },
                            data={
                                "kind": "analysis_received",
                                "analysis_id": str(analysis.id),
                            },
                            app_scope="doctor",
                        )
            except Exception:
                pass

        analysis.refresh_from_db()
        return Response(
            AnalysisDetailSerializer(analysis).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Doctor analizni ko'rdim — 'KO'RILDI' statusiga o'tkazish (doctor)",
        request=None,
        responses=AnalysisMarkSeenByDoctorResponseSerializer,
        description=(
            "Doctor app analiz detail screen ochilganda avtomatik chaqiriladi. "
            "Idempotent — qaytadan chaqirsa vaqt o'zgarmaydi. "
            "SUBMITTED status'da bo'lgan analiz uchun ishlaydi (sharh yozilmagan)."
        ),
    )
    @action(detail=True, methods=["post"], url_path="mark-seen-by-doctor")
    def mark_seen_by_doctor(self, request, pk=None):

        analysis = self.get_object()
        if get_request_role(request) != "doctor":
            return Response(
                {"detail": "Faqat shifokor ko'rdim deb belgilay oladi."}, status=403
            )

        profile = getattr(request.user, "doctor_profile", None)
        is_assigned = analysis.doctor_id == request.user.id
        is_recipient = (
            analysis.source == Analysis.Source.PATIENT_UPLOADED
            and profile is not None
            and analysis.recipients.filter(id=profile.id).exists()
        )
        if not (is_assigned or is_recipient):
            return Response(
                {"detail": "Bu analizni ko'rish huquqi yo'q."}, status=403
            )

        if analysis.doctor_viewed_at is None:
            analysis.doctor_viewed_at = timezone.now()
            analysis.save(update_fields=["doctor_viewed_at", "updated_at"])

        from ..serializers import _compute_ui_status

        return Response(
            {
                "id": analysis.id,
                "doctor_viewed_at": analysis.doctor_viewed_at,
                "ui_status": _compute_ui_status(analysis),
            }
        )

    @extend_schema(
        summary="Analizni o'chirish (faqat patient_uploaded, bemor o'zi)",
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.patient_id != request.user.id:
            return Response(
                {"detail": "Faqat o'zingiz yuklagan analizni o'chira olasiz."},
                status=403,
            )
        if instance.source != Analysis.Source.PATIENT_UPLOADED:
            return Response(
                {
                    "detail": (
                        "Doctor tayinlagan analizni o'chirib bo'lmaydi. "
                        "Buning o'rniga `cancel` action'ni ishlating."
                    )
                },
                status=400,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
