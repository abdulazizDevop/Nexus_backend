from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar
from .common import _get_doctor_profile,_not_found


@extend_schema(tags=["Payments - Doctor (Wallet)"])
class DoctorPayoutCardViewSet(viewsets.ViewSet):
    """Doctor pul yechish kartalari — bir nechta saqlash mumkin, bittasi primary."""

    permission_classes = [IsVerifiedDoctor]
    queryset = DoctorPayoutCard.objects.none()
    serializer_class = DoctorPayoutCardSerializer

    def _get_profile(self, request):
        return getattr(request.user, "doctor_profile", None)

    @extend_schema(
        summary="Mening kartalarim",
        responses=DoctorPayoutCardSerializer(many=True),
    )
    def list(self, request):
        profile = self._get_profile(request)
        if not profile:
            return Response([])
        cards = DoctorPayoutCard.objects.filter(doctor=profile)
        return Response(DoctorPayoutCardSerializer(cards, many=True).data)

    @extend_schema(
        summary="Karta ma'lumotini ATMOS'dan olish (saqlamasdan)",
        description=(
            "Karta raqamini ATMOS'ga jo'natadi va karta egasining ismi, banki, "
            "telefon raqami va SMS holatini qaytaradi. Mobile bu ma'lumotni "
            "foydalanuvchiga ko'rsatib **tasdiqlatadi**, keyin POST /doctor/cards/ "
            "orqali haqiqatan saqlaydi.\n\n"
            "Karta noto'g'ri yoki ATMOS topa olmasa — 400 qaytadi.\n\n"
            "Body: `{\"card_number\": \"8600...\"}` (16 raqam, bo'shliqsiz)"
        ),
        request={
            "type": "object",
            "properties": {"card_number": {"type": "string"}},
            "required": ["card_number"],
        },
        responses={
            200: OpenApiResponse(
                description=(
                    "Atmos /info dan kelgan ma'lumot: "
                    "name, pan (masked), expiry, phone, bank_name, processing_type, sms, "
                    "atmos_asl_card_id."
                )
            ),
            400: OpenApiResponse(description="Karta topilmadi yoki ATMOS xatosi"),
        },
    )
    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request):
        """ATMOS /info chaqirib karta ma'lumotini qaytaradi (saqlamasdan).

        Mobile bu ma'lumotni foydalanuvchiga ko'rsatadi va tasdiqlatadi.
        Faqat tasdiqlangach POST /doctor/cards/ orqali saqlanadi.
        """
        from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

        card_number = (request.data.get("card_number") or "").replace(" ", "").strip()
        if not card_number.isdigit() or len(card_number) != 16:
            return Response(
                {"detail": "Karta raqami 16 ta raqamdan iborat bo'lishi kerak."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not atmos_asl_client.is_configured():
            return Response(
                {"detail": "ATMOS ASL sozlanmagan."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            resp = atmos_asl_client.card_info(card_number)
        except AtmosAslError as exc:
            # 500 = card not found, 200 = auth, va h.k.
            if str(exc.code) == "500":
                msg = "Karta ATMOS tizimida topilmadi. Raqamni tekshiring."
            else:
                msg = exc.description or "ATMOS xatosi"
            return Response(
                {"detail": msg, "code": exc.code},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = resp.get("data") or {}
        return Response(
            {
                "atmos_asl_card_id": data.get("id"),
                "name": data.get("name", ""),
                "pan": data.get("pan", ""),
                "expiry": data.get("expiry", ""),
                "phone": data.get("phone"),
                "sms_enabled": data.get("sms"),
                "bank_name": data.get("bank_name") or "",
                "bank_mfo": data.get("bank_mfo") or "",
                "processing_type": data.get("processing_type", ""),
                "message": (
                    "Iltimos, ma'lumotlarni tekshiring va o'z kartangiz ekanini "
                    "tasdiqlang. Karta noto'g'ri bo'lsa, pul boshqa odamga ketadi!"
                ),
            }
        )

    @extend_schema(
        request=DoctorPayoutCardSerializer,
        responses={
            201: DoctorPayoutCardSerializer,
            400: OpenApiResponse(description="Validatsiya yoki duplicate karta"),
        },
        summary="Yangi karta qo'shish (preview tasdiqlangach)",
        description=(
            "Mobile bu endpointga `/preview/` natijasini foydalanuvchi tasdiqlagandan "
            "keyin chaqiradi. Body'da `card_holder` (ATMOS'dan kelgan ism), bank_name "
            "va boshqalar bo'ladi."
        ),
    )
    def create(self, request):
        profile = _get_doctor_profile(request)
        serializer = DoctorPayoutCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Duplicate tekshiruv (UniqueConstraint ga qadar — user-friendly xato)
        if DoctorPayoutCard.objects.filter(
            doctor=profile, card_number=serializer.validated_data["card_number"]
        ).exists():
            return Response(
                {"detail": "Bu karta allaqachon qo'shilgan."}, status=400
            )

        with transaction.atomic():
            is_first = not DoctorPayoutCard.objects.filter(doctor=profile).exists()
            card = DoctorPayoutCard.objects.create(
                doctor=profile,
                is_primary=is_first,  # birinchi karta avtomatik primary
                **serializer.validated_data,
            )
        logger.info(
            "Doctor card qo'shildi: doctor=%s card=%s primary=%s",
            profile.id, card.id, card.is_primary,
        )
        return Response(DoctorPayoutCardSerializer(card).data, status=201)

    @extend_schema(
        summary="Kartani o'chirish",
        responses={
            204: OpenApiResponse(description="O'chirildi"),
            404: OpenApiResponse(description="Topilmadi"),
        },
    )
    def destroy(self, request, pk=None):
        profile = self._get_profile(request)
        if not profile:
            return _not_found()
        card = DoctorPayoutCard.objects.filter(pk=pk, doctor=profile).first()
        if not card:
            return _not_found()

        was_primary = card.is_primary
        with transaction.atomic():
            card.delete()
            # Primary o'chirilsa, eng eski qolgan kartani primary qilamiz
            if was_primary:
                next_card = (
                    DoctorPayoutCard.objects.filter(doctor=profile)
                    .order_by("created_at")
                    .first()
                )
                if next_card:
                    DoctorPayoutCard.objects.filter(pk=next_card.pk).update(
                        is_primary=True
                    )
        return Response(status=204)

    @extend_schema(
        request=None,
        responses=DoctorPayoutCardSerializer,
        summary="Kartani asosiy (primary) qilish",
    )
    @action(detail=True, methods=["post"], url_path="set-primary")
    def set_primary(self, request, pk=None):
        profile = self._get_profile(request)
        if not profile:
            return _not_found()
        card = DoctorPayoutCard.objects.filter(pk=pk, doctor=profile).first()
        if not card:
            return _not_found()
        card.make_primary()
        return Response(DoctorPayoutCardSerializer(card).data)


# ============ Doctor wallet (Hamyon) ============


@extend_schema(tags=["Payments - Doctor (Wallet)"])
class DoctorWalletSummaryView(APIView):
    """Hamyon bosh ekrani uchun: balans, primary karta, oylik kirim + delta, jami yechilgan."""

    permission_classes = [IsVerifiedDoctor]
    serializer_class = WalletSummarySerializer

    @extend_schema(summary="Hamyon umumiy ma'lumotlar", responses=WalletSummarySerializer)
    def get(self, request):
        profile = _get_doctor_profile(request)
        balance, _ = DoctorBalance.objects.get_or_create(doctor=profile)

        primary_card = (
            DoctorPayoutCard.objects.filter(doctor=profile, is_primary=True).first()
            or DoctorPayoutCard.objects.filter(doctor=profile).first()
        )
        cards_count = DoctorPayoutCard.objects.filter(doctor=profile).count()

        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # O'tgan oyning birinchi kuni
        prev_month_end = month_start - timezone.timedelta(seconds=1)
        prev_month_start = prev_month_end.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        purchases = DoctorTariffPurchase.objects.filter(doctor=profile)
        this_month_total = purchases.filter(created_at__gte=month_start).aggregate(
            t=Sum("doctor_earnings")
        )["t"] or Decimal("0")
        prev_month_total = purchases.filter(
            created_at__gte=prev_month_start, created_at__lt=month_start
        ).aggregate(t=Sum("doctor_earnings"))["t"] or Decimal("0")

        if prev_month_total > 0:
            delta_pct = float(
                (this_month_total - prev_month_total) / prev_month_total * 100
            )
            delta_pct = round(delta_pct, 1)
        else:
            delta_pct = None
        if delta_pct is None:
            direction = "flat"
        elif delta_pct > 0:
            direction = "up"
        elif delta_pct < 0:
            direction = "down"
        else:
            direction = "flat"

        completed_payouts = PayoutRequest.objects.filter(
            doctor=profile, status=PayoutRequest.Status.COMPLETED
        )
        last_payout = completed_payouts.order_by("-processed_at").first()

        data = {
            "balance": balance.balance,
            "held_amount": balance.held_amount,
            "available_balance": balance.available_balance,
            "primary_card": (
                {
                    "id": primary_card.id,
                    "card_type": primary_card.card_type,
                    "card_last4": primary_card.card_last4,
                    "card_holder": primary_card.card_holder,
                    "expiry": primary_card.expiry_display,
                }
                if primary_card
                else None
            ),
            "cards_count": cards_count,
            "this_month": {
                "amount": this_month_total,
                "delta_percent": delta_pct,
                "delta_direction": direction,
            },
            "withdrawn": {
                "total": balance.total_withdrawn,
                "last_at": last_payout.processed_at if last_payout else None,
            },
            # Minimal pul yechish summasi (sozlanadigan) — frontend validatsiyasi uchun
            "min_payout": SystemSetting.get(
                PAYOUT_MIN_AMOUNT_KEY, PAYOUT_MIN_AMOUNT_DEFAULT
            ),
        }
        return Response(WalletSummarySerializer(data).data)


@extend_schema(tags=["Payments - Doctor (Wallet)"])
class DoctorWalletOperationsView(APIView):
    """Kirim + chiqim feed — Hamyon ekranidagi 'Operatsiyalar' uchun.

    Pagination: oddiy `page` + `page_size` (default 20). Kirim
    (DoctorTariffPurchase) va chiqim (PayoutRequest) Pythonda merge
    qilinadi va created_at DESC bo'yicha tartiblanadi.
    """

    permission_classes = [IsVerifiedDoctor]
    serializer_class = WalletOperationSerializer
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    @extend_schema(
        summary="Operatsiyalar feed (kirim + chiqim)",
        parameters=[
            OpenApiParameter(
                name="type",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Filter: all (default) | income | payout",
                required=False,
                enum=["all", "income", "payout"],
            ),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: OpenApiResponse(
                description=(
                    '{"count": int, "next": bool, "results": WalletOperation[]}'
                ),
            ),
        },
    )
    def get(self, request):
        profile = _get_doctor_profile(request)

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(
                self.MAX_PAGE_SIZE,
                max(1, int(request.query_params.get("page_size", self.DEFAULT_PAGE_SIZE))),
            )
        except (TypeError, ValueError):
            page_size = self.DEFAULT_PAGE_SIZE

        filt = request.query_params.get("type", "all")
        if filt not in ("all", "income", "payout", "topup", "commission"):
            filt = "all"

        start = (page - 1) * page_size
        end = start + page_size

        # Global created_at bo'yicha to'g'ri sahifalash uchun har turdan
        # eng yangi `end + 1` ta yozuvni olamiz: global top-N har bir manbaning
        # top-N qism to'plamida bo'lgani uchun bu page bo'lagini aniq qoplaydi.
        # `count` esa har turning HAQIQIY umumiy soni yig'indisi (kesilgan oyna emas).
        fetch_limit = end + 1

        total_income = 0
        total_payout = 0
        total_topup = 0
        total_commission = 0
        incomes = []
        if filt in ("all", "income"):
            # Faqat ONLINE xaridlar balansga earnings qo'shadi. Offline (naqd)
            # xaridda doctor naqdni o'zi olgan — balansga kirmaydi (komissiyasi
            # alohida 'commission' operatsiyasi sifatida ko'rinadi).
            income_base = DoctorTariffPurchase.objects.filter(
                doctor=profile, source=DoctorTariffPurchase.Source.ONLINE
            )
            total_income = income_base.count()
            qs_in = income_base.select_related("patient", "tariff")[:fetch_limit]
            for p in qs_in:
                tariff_name = (
                    p.tariff.name
                    if p.tariff
                    else (p.tariff_snapshot.get("name") or "Tarif")
                )
                patient_name = getattr(p.patient, "full_name", "") or ""
                # short ism: "Bekjan Y."
                parts = patient_name.split() if patient_name else []
                if len(parts) >= 2:
                    short = f"{parts[0]} {parts[1][:1]}."
                else:
                    short = patient_name
                incomes.append(
                    {
                        "kind": "income",
                        "id": p.id,
                        "amount": p.doctor_earnings,
                        "title": tariff_name,
                        "subtitle": short,
                        "created_at": p.created_at,
                        "detail_status": None,
                        "detail_status_label": "",
                    }
                )

        if filt in ("all", "payout"):
            payout_base = PayoutRequest.objects.filter(doctor=profile)
            total_payout = payout_base.count()
            qs_out = payout_base[:fetch_limit]
            for r in qs_out:
                type_label = r.get_card_type_display() if r.card_type else "Karta"
                incomes_neg_title = f"Pul yechildi · {type_label}"
                subtitle = (
                    f"····{r.card_last4}" if r.card_last4 else (r.card_holder or "")
                )
                incomes.append(
                    {
                        "kind": "payout",
                        "id": r.id,
                        "amount": -r.amount,
                        "title": incomes_neg_title,
                        "subtitle": subtitle,
                        "created_at": r.created_at,
                        "detail_status": r.detail_status,
                        "detail_status_label": r.detail_status_label,
                    }
                )

        if filt in ("all", "topup"):
            topup_base = BalanceTopup.objects.filter(doctor=profile)
            total_topup = topup_base.count()
            for bt in topup_base[:fetch_limit]:
                incomes.append(
                    {
                        "kind": "topup",
                        "id": bt.id,
                        "amount": bt.amount,
                        "title": "Balans to'ldirildi",
                        "subtitle": "",
                        "created_at": bt.created_at,
                        "detail_status": None,
                        "detail_status_label": "",
                    }
                )

        if filt in ("all", "commission"):
            comm_base = OfflinePayment.objects.filter(
                doctor=profile, status=OfflinePayment.Status.CONFIRMED
            ).select_related("patient")
            total_commission = comm_base.count()
            for op in comm_base[:fetch_limit]:
                patient_name = getattr(op.patient, "full_name", "") or ""
                parts = patient_name.split() if patient_name else []
                short = (
                    f"{parts[0]} {parts[1][:1]}." if len(parts) >= 2 else patient_name
                )
                incomes.append(
                    {
                        "kind": "commission",
                        "id": op.id,
                        "amount": -(op.commission_amount or Decimal("0")),
                        "title": "Naqd komissiya",
                        "subtitle": short,
                        "created_at": op.processed_at or op.created_at,
                        "detail_status": None,
                        "detail_status_label": "",
                    }
                )

        # Merge (incomes ro'yxati barcha turlarni o'z ichiga oladi)
        incomes.sort(key=lambda x: x["created_at"], reverse=True)
        page_items = incomes[start:end]
        total_count = total_income + total_payout + total_topup + total_commission
        has_more = total_count > end

        return Response(
            {
                "count": total_count,  # haqiqiy umumiy son (kesilgan oyna emas)
                "next": has_more,
                "results": WalletOperationSerializer(page_items, many=True).data,
            }
        )


# ============ Doctor payout (pul yechish) ============


def _build_flow_summary_success(payout, result: dict) -> str:
    """Auto-ASL muvaffaqiyatli tugaganda foydalanuvchi uchun matn.

    state: 4=FINISHED, 13=PENDING, 5=FAILED
    """
    state = result.get("state")
    tx_id = result.get("transaction_id")
    last4 = payout.card_last4 or "****"

    if result.get("completed"):  # state=4
        return (
            f"✅ So'rov yaratildi\n"
            f"✅ ATMOS ASL'da karta registratsiyasi\n"
            f"✅ ATMOS tranzaksiya yaratildi (id={tx_id})\n"
            f"✅ Pul kartaga muvaffaqiyatli yuborildi (****{last4})\n"
            f"💰 Sizning balansingiz {payout.amount} so'mga kamaytirildi."
        )
    if result.get("polling"):  # state=13 PENDING
        return (
            f"✅ So'rov yaratildi\n"
            f"✅ ATMOS ASL'da karta registratsiyasi\n"
            f"✅ ATMOS tranzaksiya yaratildi (id={tx_id})\n"
            f"⏳ ATMOS pul yuborilmoqda — javob kutilmoqda...\n"
            f"🔁 Har 5 sekundda tekshirilib boriladi (max 5 daqiqa)."
        )
    if state == 5:  # FAILED
        return (
            f"✅ So'rov yaratildi\n"
            f"✅ ATMOS ASL'da karta registratsiyasi\n"
            f"✅ ATMOS tranzaksiya yaratildi (id={tx_id})\n"
            f"❌ ATMOS pul yubora olmadi — tranzaksiya rad etildi.\n"
            f"💰 Balansingiz tegmadi — qaytadan urinib ko'ring."
        )
    return f"⚠️ ATMOS notanish holatda (state={state}). Admin tekshirishi kerak."


def _build_flow_summary_error(exc) -> str:
    """ASL xato bo'lganda foydalanuvchi uchun friendly matn.

    Auto-retry har 5 daqiqada — foydalanuvchi qayta yuborishi shart emas.
    """
    code = exc.code

    if code in (100, 101, 102, 103):
        return (
            "✅ So'rov yaratildi va navbatga qo'shildi\n"
            "⚠️ ATMOS vaqtinchalik xato qaytardi (tarmoq yoki ichki xato)\n"
            f"📝 Xato: {exc.description}\n"
            "🔁 Tizim har 5 daqiqada qaytadan urinib boradi — siz hech narsa qilmaysiz."
        )
    if code in ("invalid_response", "token_error"):
        return (
            "✅ So'rov yaratildi va navbatga qo'shildi\n"
            "❌ ATMOS ASL serveriga ulana olinmadi (token yoki sandbox muammosi)\n"
            f"📝 Xato: {exc.description}\n"
            "🔁 Tizim har 5 daqiqada qaytadan urinib boradi — siz hech narsa qilmaysiz.\n"
            "ℹ️ Sandbox sozlamalar Atmos tomonida aktivlashganda darrov tushadi."
        )
    if code == 500:
        return (
            "✅ So'rov yaratildi\n"
            "❌ ATMOS'da karta topilmadi\n"
            f"📝 {exc.description}\n"
            "💡 Karta raqami noto'g'ri yoki ATMOS bilan ishlamaydi — boshqa karta kiriting."
        )
    if code == 300:
        return (
            "✅ So'rov yaratildi\n"
            "❌ Bizning ATMOS depozitida pul yetarli emas\n"
            f"📝 {exc.description}\n"
            "💡 Admin'ga xabar qiling (depozitni to'ldirishi kerak)."
        )
    if code == 200:
        return (
            "✅ So'rov yaratildi\n"
            "❌ ATMOS auth xatosi — credentials noto'g'ri yoki muddati o'tgan\n"
            f"📝 {exc.description}\n"
            "💡 Admin ATMOS sozlamalarini tekshirishi kerak."
        )
    if code == 700:
        return (
            "✅ So'rov yaratildi\n"
            "❌ ATMOS limit xatosi (kunlik/oylik chegara oshib ketdi)\n"
            f"📝 {exc.description}\n"
            "💡 Ertaga qaytadan urinib ko'ring yoki kichikroq summa bilan."
        )
    return (
        "✅ So'rov yaratildi va navbatga qo'shildi\n"
        f"❌ ATMOS xatosi: {exc.description} (code={code})\n"
        "🔁 Tizim har 5 daqiqada qaytadan urinib boradi."
    )


@extend_schema(tags=["Payments - Doctor (Wallet)"])
class DoctorPayoutRequestViewSet(viewsets.ViewSet):
    """Doctor pul yechish so'rovlari (Yechishlar tarixi ekrani)."""

    permission_classes = [IsVerifiedDoctor]
    queryset = PayoutRequest.objects.none()
    serializer_class = PayoutRequestSerializer

    # Frontend filter -> queryset filter
    _FILTER_MAP = {
        "all": None,
        "in_progress": {"status": PayoutRequest.Status.PENDING},
        "completed": {"status": PayoutRequest.Status.COMPLETED},
        "rejected": {
            "status__in": [
                PayoutRequest.Status.REJECTED,
                PayoutRequest.Status.CANCELLED,
            ]
        },
    }

    def get_serializer_class(self):
        if self.action == "create":
            return PayoutRequestCreateSerializer
        return PayoutRequestSerializer

    def _get_profile(self, request):
        return getattr(request.user, "doctor_profile", None)

    @extend_schema(
        summary="Mening so'rovlarim (Yechishlar tarixi + stats)",
        responses=PayoutListResponseSerializer,
        parameters=[
            OpenApiParameter(
                name="filter",
                type=str,
                location=OpenApiParameter.QUERY,
                description="all | in_progress | completed | rejected",
                required=False,
                enum=list(_FILTER_MAP.keys()),
            ),
        ],
    )
    def list(self, request):
        profile = self._get_profile(request)
        if not profile:
            empty = {
                "stats": {
                    "total_withdrawn": Decimal("0"),
                    "in_progress_total": Decimal("0"),
                },
                "filter_counts": {
                    "all": 0,
                    "in_progress": 0,
                    "completed": 0,
                    "rejected": 0,
                },
                "results": [],
            }
            return Response(empty)

        base_qs = PayoutRequest.objects.filter(doctor=profile)

        # Stats — barcha vaqtlar uchun
        total_withdrawn = base_qs.filter(
            status=PayoutRequest.Status.COMPLETED
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0")
        in_progress_total = base_qs.filter(
            status=PayoutRequest.Status.PENDING
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0")

        # Filter counts
        filter_counts = {
            "all": base_qs.count(),
            "in_progress": base_qs.filter(status=PayoutRequest.Status.PENDING).count(),
            "completed": base_qs.filter(status=PayoutRequest.Status.COMPLETED).count(),
            "rejected": base_qs.filter(
                status__in=[
                    PayoutRequest.Status.REJECTED,
                    PayoutRequest.Status.CANCELLED,
                ]
            ).count(),
        }

        filt = request.query_params.get("filter", "all")
        if filt not in self._FILTER_MAP:
            filt = "all"
        rule = self._FILTER_MAP[filt]
        results_qs = base_qs if rule is None else base_qs.filter(**rule)

        return Response(
            {
                "stats": {
                    "total_withdrawn": total_withdrawn,
                    "in_progress_total": in_progress_total,
                },
                "filter_counts": filter_counts,
                "results": PayoutRequestSerializer(results_qs, many=True).data,
            }
        )

    @extend_schema(
        summary="So'rov batafsil",
        responses=PayoutRequestSerializer,
    )
    def retrieve(self, request, pk=None):
        profile = self._get_profile(request)
        if not profile:
            return _not_found()
        payout = PayoutRequest.objects.filter(pk=pk, doctor=profile).first()
        if not payout:
            return _not_found()
        return Response(PayoutRequestSerializer(payout).data)

    @extend_schema(
        request=PayoutRequestCreateSerializer,
        responses={
            201: PayoutRequestSerializer,
            400: OpenApiResponse(description="Validatsiya xatosi"),
        },
        summary="Yangi pul yechish so'rovi (saqlangan karta orqali)",
    )
    def create(self, request):
        profile = _get_doctor_profile(request)
        balance, _ = DoctorBalance.objects.get_or_create(doctor=profile)

        serializer = PayoutRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]
        card_id = serializer.validated_data["card_id"]

        card = DoctorPayoutCard.objects.filter(pk=card_id, doctor=profile).first()
        if not card:
            return Response(
                {"detail": "Karta topilmadi yoki sizga tegishli emas."},
                status=400,
            )

        # Bank ish kuni gate (Du-Ju, bayram emas)
        if SystemSetting.get(
            PAYOUT_BUSINESS_DAYS_ONLY_KEY, PAYOUT_BUSINESS_DAYS_ONLY_DEFAULT
        ):
            if not is_bank_business_day():
                return Response(
                    {
                        "detail": (
                            "Pul yechish so'rovi faqat bank ish kunlarida "
                            "(Du-Ju, bayramdan tashqari) qabul qilinadi."
                        ),
                    },
                    status=400,
                )

        # Min amount
        min_amount = SystemSetting.get_decimal(
            PAYOUT_MIN_AMOUNT_KEY, PAYOUT_MIN_AMOUNT_DEFAULT
        )
        if amount < min_amount:
            return Response(
                {"detail": f"Minimal so'rov summasi: {min_amount} so'm."},
                status=400,
            )

        max_pending = SystemSetting.get_int(
            PAYOUT_MAX_PENDING_KEY, PAYOUT_MAX_PENDING_DEFAULT
        )

        # XAVFSIZLIK: balans tekshiruvi + payout yaratish ATOMIC + select_for_update
        # bilan — konkurent so'rovlar (retry/race) double-spend qila olmasin,
        # balansni manfiyga olib bormasin. held/pending qulf ostida qayta hisoblanadi.
        with transaction.atomic():
            balance = DoctorBalance.objects.select_for_update().get(pk=balance.pk)
            pending_qs = PayoutRequest.objects.filter(
                doctor=profile, status=PayoutRequest.Status.PENDING
            )
            pending_total = pending_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
            held_amount = balance.held_amount
            available = balance.balance - held_amount - pending_total
            if amount > available:
                return Response(
                    {
                        "detail": "Mablag' yetarli emas yoki bir qismi hali muzlatilgan (hold).",
                        "balance": str(balance.balance),
                        "held_amount": str(held_amount),
                        "pending_total": str(pending_total),
                        "available": str(available),
                    },
                    status=400,
                )
            if pending_qs.count() >= max_pending:
                return Response(
                    {
                        "detail": (
                            f"Sizda {max_pending} ta kutilayotgan so'rov bor. "
                            "Avval ulardan biri yakunlanishini kuting."
                        )
                    },
                    status=400,
                )

            payout = PayoutRequest.objects.create(
                doctor=profile,
                amount=amount,
                card=card,
                card_type=card.card_type,
                card_number=card.card_number,
                card_holder=card.card_holder,
                bank_name=card.bank_name,
            )
        logger.info(
            "Payout request yaratildi: doctor=%s amount=%s payout=%s card=%s balance=%s",
            profile.id, amount, payout.id, card.id, balance.balance,
        )

        # Soliq-style avto-payout: ATMOS ASL sozlangan bo'lsa, payout darrov
        # ishga tushiriladi. Admin tasdiqlashi shart emas.
        # state=4 (FINISHED) → balans yechiladi, payout completed
        # state=13 (PENDING) → Celery polling
        # state=5 (FAILED)  → balans tegmaydi, status=rejected
        # ASL xatoligi (timeout, 401, ...) → payout pending qoladi, auto-retry
        from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

        if not atmos_asl_client.is_configured():
            return Response(
                {
                    **PayoutRequestSerializer(payout).data,
                    "flow_summary": (
                        "✅ So'rov yaratildi va navbatga qo'shildi.\n"
                        "⚠️ ATMOS ASL backend'da sozlanmagan — payout admin tomonidan "
                        "qo'lda bajariladi yoki konfiguratsiya tugagach avtomatik tushadi."
                    ),
                },
                status=201,
            )

        from ..atmos_asl_service import initiate_atmos_payout
        try:
            result = initiate_atmos_payout(payout)
            payout.refresh_from_db()
            logger.info(
                "Auto-ASL payout: payout=%s state=%s completed=%s polling=%s",
                payout.id, result.get("state"),
                result.get("completed"), result.get("polling"),
            )
            flow_summary = _build_flow_summary_success(payout, result)
            return Response(
                {
                    **PayoutRequestSerializer(payout).data,
                    "atmos_result": {
                        "state": result.get("state"),
                        "transaction_id": result.get("transaction_id"),
                        "completed": result.get("completed", False),
                        "polling": result.get("polling", False),
                    },
                    "flow_summary": flow_summary,
                },
                status=201,
            )
        except AtmosAslError as exc:
            # Atmos xatosi — payout pending qoldiramiz, auto-retry har 5 daq
            logger.warning(
                "Auto-ASL xato (auto-retry kutilmoqda): payout=%s code=%s desc=%s",
                payout.id, exc.code, exc.description,
            )
            return Response(
                {
                    **PayoutRequestSerializer(payout).data,
                    "atmos_error": exc.description,
                    "atmos_error_code": exc.code,
                    "flow_summary": _build_flow_summary_error(exc),
                },
                status=201,
            )

    @extend_schema(
        summary="Pending so'rovni bekor qilish",
        request=None,
        responses={
            200: PayoutRequestSerializer,
            400: OpenApiResponse(description="Faqat pending so'rovni bekor qilish mumkin"),
        },
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        profile = self._get_profile(request)
        if not profile:
            return _not_found()
        payout = PayoutRequest.objects.filter(pk=pk, doctor=profile).first()
        if not payout:
            return _not_found()
        if payout.status != PayoutRequest.Status.PENDING:
            return Response(
                {"detail": "Faqat 'pending' holatdagi so'rovni bekor qilish mumkin."},
                status=400,
            )
        payout.status = PayoutRequest.Status.CANCELLED
        payout.processed_at = timezone.now()
        payout.save(update_fields=["status", "processed_at"])
        return Response(PayoutRequestSerializer(payout).data)


