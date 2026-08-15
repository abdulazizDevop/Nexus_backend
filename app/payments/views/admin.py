from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar
from .common import _annotate_sum_fields,_parse_date_range,_parse_page,_require_asl_configured,_tiyin_to_sum


@extend_schema(tags=["Payments - Admin"])
class ProPlanAdminViewSet(viewsets.ModelViewSet):
    """Admin: Pro planlarni boshqarish"""

    queryset = ProPlan.objects.all()
    serializer_class = ProPlanSerializer
    permission_classes = [IsSuperOrSimpleAdmin]


@extend_schema(tags=["Payments - Admin"])
class ProFeatureFlagAdminViewSet(viewsets.ModelViewSet):
    """Admin: Pro feature flagsni boshqarish"""

    queryset = ProFeatureFlag.objects.all()
    serializer_class = ProFeatureFlagSerializer
    permission_classes = [IsSuperOrSimpleAdmin]


@extend_schema(tags=["Payments - Admin"])
class SystemSettingAdminViewSet(viewsets.ModelViewSet):
    """Admin: Sistema sozlamalari (komissiya %, va h.k.)"""

    queryset = SystemSetting.objects.all()
    serializer_class = SystemSettingSerializer
    permission_classes = [IsSuperOrSimpleAdmin]
    lookup_field = "key"


def _notify_tariff_status(tariff, catalog_key, notif_type, extra_params=None):
    """Tarif moderatsiya statusi o'zgarganda doctorga push yuboradi.

    approve/reject bir xil oqimni bajaradi: doctor tilini aniqlash,
    tariff.name'ni o'sha tilda tanlash, catalog'dan title/body render qilish,
    notify_user.delay(app_scope='doctor'). Faqat catalog_key/type/params farq qiladi.
    """
    doctor_user = tariff.doctor.user
    doctor_lang = (
        getattr(getattr(doctor_user, "settings", None), "language", None) or "uz"
    )
    params = {"tariff_name": pick_translation(tariff.name, doctor_lang)}
    if extra_params:
        params.update(extra_params)
    try:
        title, body = render_notif(catalog_key, doctor_lang, params=params)
        notify_user.delay(
            user_id=doctor_user.id,
            type=notif_type,
            title=title,
            body=body,
            data={"tariff_id": str(tariff.id)},
            app_scope="doctor",
        )
    except Exception:
        pass


@extend_schema(tags=["Payments - Admin"])
class DoctorTariffAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: Doctor tariflari moderatsiyasi"""

    serializer_class = DoctorTariffAdminSerializer
    permission_classes = [IsSuperOrSimpleAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DoctorTariff.objects.none()
        qs = DoctorTariff.objects.all().select_related("doctor__user")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @extend_schema(summary="Tariflar ro'yxati (filter: status)")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Tarif batafsil")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Tarifni tasdiqlash")
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        tariff = self.get_object()
        tariff.status = DoctorTariff.Status.APPROVED
        tariff.rejection_reason = ""
        tariff.save(update_fields=["status", "rejection_reason"])

        # Audit FAZA D + A1 — catalog orqali doctor tilida.
        _notify_tariff_status(
            tariff, "tariff_approved", Notification.Type.TARIFF_APPROVED
        )

        return Response(DoctorTariffAdminSerializer(tariff).data)

    @extend_schema(request=RejectTariffSerializer, summary="Tarifni rad etish")
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        tariff = self.get_object()
        serializer = RejectTariffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tariff.status = DoctorTariff.Status.REJECTED
        tariff.rejection_reason = serializer.validated_data["reason"]
        tariff.save(update_fields=["status", "rejection_reason"])

        # Audit FAZA D + A1 — catalog orqali doctor tilida.
        _notify_tariff_status(
            tariff,
            "tariff_rejected",
            Notification.Type.TARIFF_REJECTED,
            extra_params={"reason": tariff.rejection_reason},
        )

        return Response(DoctorTariffAdminSerializer(tariff).data)


@extend_schema(tags=["Payments - Admin"])
class PaymentAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: Barcha to'lovlar ro'yxati"""

    serializer_class = PaymentAdminSerializer
    permission_classes = [IsSuperOrSimpleAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        qs = Payment.objects.all().select_related("user")
        for key in ("status", "provider", "purpose"):
            val = self.request.query_params.get(key)
            if val:
                qs = qs.filter(**{key: val})

        # Sana validatsiyasi: noto'g'ri formatdagi date string Django'da
        # ValidationError qiladi (500 chiqaradi). User-friendly 400 javob qaytarish
        # uchun avval parse qilamiz va xato bo'lsa silent skip (filter qo'llanmaydi).
        for param, lookup in (("date_from", "gte"), ("date_to", "lte")):
            val = self.request.query_params.get(param)
            if not val:
                continue
            try:
                parsed = datetime.strptime(val, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                # Noto'g'ri format — DRF view'da exception bersak 500 chiqadi.
                # Faqat shu filter'ni o'tkazib yuboramiz; admin notice oladi
                # bo'sh yoki to'liq ro'yxat orqali.
                continue
            qs = qs.filter(**{f"created_at__date__{lookup}": parsed})
        return qs


@extend_schema(tags=["Payments - Admin"])
class DoctorBalanceAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: Hamma doctor balanslari"""

    queryset = DoctorBalance.objects.all().select_related("doctor__user")
    serializer_class = DoctorBalanceSerializer
    permission_classes = [IsSuperOrSimpleAdmin]


@extend_schema(tags=["Payments - Admin"])
class PayoutRequestAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin: Doctor pul yechish so'rovlarini boshqarish."""

    serializer_class = PayoutRequestAdminSerializer
    permission_classes = [IsSuperOrSimpleAdmin]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PayoutRequest.objects.none()
        qs = PayoutRequest.objects.all().select_related(
            "doctor__user", "doctor__balance", "processed_by"
        )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        doctor_id = self.request.query_params.get("doctor_id")
        if doctor_id:
            qs = qs.filter(doctor_id=doctor_id)
        return qs

    @extend_schema(
        summary="Payout so'rovlari ro'yxati",
        parameters=[
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="doctor_id", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="So'rov batafsil")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        responses=PayoutRequestAdminSerializer,
        summary="ATMOS ASL fallback — auto-payout xato bo'lganda qayta urinish",
        description=(
            "Doctor `/doctor/payouts/` chaqirsa, ASL avtomatik triggerlanadi. "
            "Lekin ASL xato qaytarsa (timeout, 401, vaqtinchalik xato) — payout "
            "`pending` qoladi. Bu endpoint shu fallback uchun: admin pending payout'ni "
            "qayta ASL orqali yuboradi. Idempotent — agar avval transaction yaratilgan "
            "bo'lsa, status tekshiriladi (qayta yaratilmaydi)."
        ),
    )
    @action(detail=True, methods=["post"], url_path="process-atmos")
    def process_atmos(self, request, pk=None):
        from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

        from ..atmos_asl_service import initiate_atmos_payout

        payout = self.get_object()
        if payout.status != PayoutRequest.Status.PENDING:
            return Response(
                {"detail": "Faqat 'pending' holatdagi so'rovni qayta ishlash mumkin."},
                status=400,
            )

        if not atmos_asl_client.is_configured():
            return Response(
                {"detail": "ATMOS ASL konfiguratsiyasi to'liq emas (USERNAME/PASSWORD)."},
                status=503,
            )

        # Balans tekshiruvi — create() dagi kabi held_amount va BOSHQA pending
        # payout'larni (joriy payout'dan tashqari) ham hisobga olamiz. Aks holda
        # bir nechta pending payout har biri balance.balance < amount tekshiruvidan
        # o'tib, jami balansdan oshib ketib, balansni manfiyga olib boradi.
        balance, _ = DoctorBalance.objects.get_or_create(doctor=payout.doctor)
        other_pending_total = (
            PayoutRequest.objects.filter(
                doctor=payout.doctor, status=PayoutRequest.Status.PENDING
            )
            .exclude(pk=payout.pk)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )
        available = balance.balance - balance.held_amount - other_pending_total
        if payout.amount > available:
            return Response(
                {
                    "detail": "Doctor balansi yetarli emas yoki bir qismi muzlatilgan (hold).",
                    "balance": str(balance.balance),
                    "held_amount": str(balance.held_amount),
                    "other_pending_total": str(other_pending_total),
                    "available": str(available),
                    "amount": str(payout.amount),
                },
                status=400,
            )

        payout.processed_by = request.user
        payout.save(update_fields=["processed_by"])

        try:
            result = initiate_atmos_payout(payout)
        except AtmosAslError as exc:
            logger.warning(
                "ASL admin process xato: payout=%s code=%s desc=%s admin=%s",
                payout.id, exc.code, exc.description, request.user.id,
            )
            return Response(
                {"detail": exc.description, "code": exc.code},
                status=400,
            )

        payout.refresh_from_db()
        logger.info(
            "ASL admin process: payout=%s state=%s polling=%s completed=%s admin=%s",
            payout.id, result.get("state"), result.get("polling"),
            result.get("completed"), request.user.id,
        )

        return Response(
            {
                **PayoutRequestAdminSerializer(payout).data,
                "atmos_result": {
                    "state": result.get("state"),
                    "transaction_id": result.get("transaction_id"),
                    "ext_id": result.get("ext_id"),
                    "completed": result.get("completed", False),
                    "polling": result.get("polling", False),
                },
            }
        )

    @extend_schema(
        responses=PayoutRequestAdminSerializer,
        summary="ATMOS ASL holatini qayta tekshirish (/id polling — 1 marta)",
    )
    @action(detail=True, methods=["post"], url_path="recheck-atmos")
    def recheck_atmos(self, request, pk=None):
        from services.payments.atmos_asl import AtmosAslError

        from ..atmos_asl_service import _check_existing

        payout = self.get_object()
        if not payout.atmos_asl_transaction_id and not payout.atmos_asl_ext_id:
            return Response(
                {"detail": "Bu payout ATMOS ASL orqali ishga tushirilmagan."},
                status=400,
            )

        try:
            result = _check_existing(payout)
        except AtmosAslError as exc:
            return Response(
                {"detail": exc.description, "code": exc.code},
                status=400,
            )

        payout.refresh_from_db()
        return Response(
            {
                **PayoutRequestAdminSerializer(payout).data,
                "atmos_result": result,
            }
        )


@extend_schema(tags=["Payments - Admin"])
class AtmosAslDepositView(APIView):
    """ATMOS ASL depozit holati — admin uchun.

    Joriy balans (saldo) va oxirgi pollanish operatsiyalari. Pasayib qolsa
    adminga bankdan to'ldirish kerakligi to'g'risida ogohlantirish.
    """

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        summary="Joriy ATMOS ASL depozit qoldig'i",
        description="GET /deposit/current chaqiriladi. saldo — tiyinda.",
    )
    def get(self, request):
        from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

        not_configured = _require_asl_configured()
        if not_configured:
            return not_configured

        try:
            resp = atmos_asl_client.get_deposit()
        except AtmosAslError as exc:
            return Response(
                {"detail": exc.description, "code": exc.code}, status=502
            )

        data = resp.get("data") or {}
        saldo_tiyin = data.get("saldo") or 0
        saldo_sum = _tiyin_to_sum(saldo_tiyin)  # tiyin → so'm

        warn_threshold = settings.ATMOS_ASL["MIN_DEPOSIT_WARN_SUM"]
        return Response(
            {
                "saldo_tiyin": saldo_tiyin,
                "saldo_sum": saldo_sum,
                "partner_id": data.get("partner_id"),
                "low_balance_warning": saldo_sum < warn_threshold,
                "warn_threshold_sum": warn_threshold,
                "raw": data,
            }
        )


@extend_schema(tags=["Payments - Admin"])
class AtmosAslTransactionsView(APIView):
    """ATMOS ASL'da bizning barcha payout tranzaksiyalarimiz — admin uchun.

    ATMOS POST /list orqali kunlar oralig'idagi tranzaksiyalarni ko'radi.
    State'lar: 2=ACCEPTED, 4=FINISHED (tushdi), 5=FAILED, 13=PENDING.
    """

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        summary="ATMOS ASL tranzaksiyalar tarixi",
        description=(
            "?from=YYYY-MM-DD&to=YYYY-MM-DD&page=1 — kunlar oralig'idagi har bir "
            "payout (ATMOS DB'sidan). Har sahifada 10 ta yozuv."
        ),
        parameters=[
            OpenApiParameter(name="from", type=str, required=False),
            OpenApiParameter(name="to", type=str, required=False),
            OpenApiParameter(name="page", type=int, required=False),
        ],
    )
    def get(self, request):
        from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

        not_configured = _require_asl_configured()
        if not_configured:
            return not_configured

        # Default: oxirgi 30 kun
        date_from, date_to = _parse_date_range(request, default_days=30)
        page = _parse_page(request)

        # ATMOS /list endpoint'i `to` ni exclusive deb interpretatsiya qiladi
        # (bugungi tranzaksiyalar tushib qoladi). +1 kun qo'shib inclusive qilamiz.
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")
            atmos_to = (to_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            atmos_to = date_to

        # ATMOS API 0-indexed page ishlatadi — UI'dan 1-chi sahifa = atmos page=0
        try:
            resp = atmos_asl_client.transaction_list(date_from, atmos_to, page - 1)
        except AtmosAslError as exc:
            return Response(
                {"detail": exc.description, "code": exc.code}, status=502
            )

        # tiyin → so'm formatlash (foydalanuvchi tiyin bilan ishlamaydi)
        data = resp.get("data") or {}
        for tx in data.get("transactions", []):
            _annotate_sum_fields(
                tx,
                [
                    ("amount", "amount_sum"),
                    ("commission_amount", "commission_sum"),
                    ("deposit_amount", "deposit_sum"),
                ],
            )

        return Response(data)


@extend_schema(tags=["Payments - Admin"])
class AtmosAslDepositHistoryView(APIView):
    """ATMOS ASL depozit operatsiyalari (pul to'ldirish/yechish) tarixi.

    Bizning ATMOS depozitimiz kunlik o'zgarishlarini ko'rsatadi:
    - CREDIT (kirim — bankdan pul to'ldirilgan)
    - DEBIT (chiqim — payout'lar uchun yechilgan)
    """

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        summary="ATMOS ASL depozit operatsiyalari tarixi",
        description=(
            "?from=YYYY-MM-DD&to=YYYY-MM-DD&page=1 — kunlar oralig'idagi "
            "depozit kirim/chiqim operatsiyalari. Bank to'ldirgan summalarni "
            "shu yerda ko'rasiz."
        ),
        parameters=[
            OpenApiParameter(name="from", type=str, required=False),
            OpenApiParameter(name="to", type=str, required=False),
            OpenApiParameter(name="page", type=int, required=False),
        ],
    )
    def get(self, request):
        from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

        not_configured = _require_asl_configured()
        if not_configured:
            return not_configured

        date_from, date_to = _parse_date_range(request, default_days=30)
        page = _parse_page(request)

        # ATMOS API 0-indexed page ishlatadi — UI 1-chi sahifa = atmos page=0
        try:
            resp = atmos_asl_client.deposit_list(date_from, date_to, page - 1)
        except AtmosAslError as exc:
            return Response(
                {"detail": exc.description, "code": exc.code}, status=502
            )

        # tiyin → so'm
        data = resp.get("data") or {}
        for op in data.get("depositList", []):
            _annotate_sum_fields(
                op,
                [
                    ("creditAmount", "creditAmount_sum"),
                    ("debitAmount", "debitAmount_sum"),
                    ("outBalance", "outBalance_sum"),
                    ("inBalance", "inBalance_sum"),
                ],
            )

        return Response(data)


@extend_schema(tags=["Payments - Admin"])
class AdminGrantProView(APIView):
    """Admin foydalanuvchiga manual Pro obuna beradi (to'lovsiz)."""

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        request=GrantProSerializer,
        responses=ProSubscriptionSerializer,
        summary="User'ga Pro obuna berish (admin qo'lda)",
        description=(
            "User'ga duration_days kun ichida amal qiladigan Pro obuna beradi. "
            "Payment yaratilmaydi (to'lovsiz), plan_snapshot ichida admin grant "
            "ma'lumotlari audit uchun saqlanadi. Faqat super/simple admin yoki root."
        ),
    )
    def post(self, request, user_id=None):

        target = User.objects.filter(id=user_id).first()
        if not target:
            return Response({"detail": "Foydalanuvchi topilmadi."}, status=404)

        serializer = GrantProSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        duration_days = serializer.validated_data["duration_days"]
        reason = serializer.validated_data.get("reason") or ""

        now = timezone.now()
        starts_at = now

        # Agar user'da allaqachon aktiv obuna bo'lsa, yangi obuna mavjudining
        # tugash vaqtidan boshlanadi (kunlarni yo'qotmaslik uchun).

        existing = get_active_pro_subscription(target)
        if existing and existing.expires_at > now:
            starts_at = existing.expires_at

        sub = ProSubscription.objects.create(
            user=target,
            plan=None,
            plan_snapshot={
                "granted_by_admin": True,
                "granted_by_user_id": request.user.id,
                "granted_by_phone": request.user.phone,
                "duration_days": duration_days,
                "reason": reason,
                "name": f"Admin grant ({duration_days} kun)",
            },
            starts_at=starts_at,
            expires_at=starts_at + timezone.timedelta(days=duration_days),
            payment=None,
        )

        return Response(ProSubscriptionSerializer(sub).data, status=201)


@extend_schema(tags=["Payments - Admin"])
class AdminRevokeProView(APIView):
    """Admin user'ning aktiv Pro obunasini bekor qiladi."""

    permission_classes = [IsSuperOrSimpleAdmin]
    serializer_class = RevokeProResponseSerializer

    @extend_schema(
        summary="User'ning aktiv Pro obunasini bekor qilish",
        description=(
            "User'ning eng yaqin expires_at vaqtini hozirgi payt'ga qo'yib, "
            "obunani darhol tugatadi. Barcha aktiv obunalarga ta'sir qiladi."
        ),
        request=None,
        responses=RevokeProResponseSerializer,
    )
    def post(self, request, user_id=None):

        target = User.objects.filter(id=user_id).first()
        if not target:
            return Response({"detail": "Foydalanuvchi topilmadi."}, status=404)

        now = timezone.now()
        updated = ProSubscription.objects.filter(
            user=target, expires_at__gt=now
        ).update(expires_at=now)

        return Response({"revoked_count": updated})


@extend_schema(tags=["Payments - Admin"])
class AdminUserProHistoryView(APIView):
    """Admin user'ning Pro obuna tarixini ko'radi."""

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        responses=ProSubscriptionSerializer(many=True),
        summary="User'ning Pro obuna tarixi",
    )
    def get(self, request, user_id=None):
        # Audit (scaling) — har sub uchun obj.plan.name JOIN qilmaslik.
        subs = (
            ProSubscription.objects.filter(user_id=user_id)
            .select_related("plan")
            .order_by("-created_at")
        )
        return Response(
            ProSubscriptionSerializer(subs, many=True, context={"request": request}).data
        )


# ============ Webhook helpers ============


