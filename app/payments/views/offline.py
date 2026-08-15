from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


def _send_offline_notif(user, notif_type, title_map, body_map, data, app_scope):
    """Offline to'lov bo'yicha bildirishnoma — recipient tilida title/body."""
    lang = getattr(getattr(user, "settings", None), "language", None) or "uz"
    try:
        notify(
            user=user,
            type=notif_type,
            title=pick_translation(title_map, lang),
            body=pick_translation(body_map, lang),
            data=data,
            app_scope=app_scope,
        )
    except Exception:
        logger.exception(
            "Offline notif yuborilmadi user=%s type=%s",
            getattr(user, "id", None), notif_type,
        )


def _notify_offline_rejected(op):
    _send_offline_notif(
        op.patient,
        Notification.Type.OFFLINE_PAYMENT_REJECTED,
        {"uz": "To'lov rad etildi", "ru": "Оплата отклонена", "cyr": "Тўлов рад этилди"},
        {
            "uz": "Naqd to'lov so'rovingiz rad etildi.",
            "ru": "Ваш запрос на наличную оплату отклонён.",
            "cyr": "Нақд тўлов сўровингиз рад этилди.",
        },
        {"kind": "offline_payment_rejected", "offline_payment_id": str(op.id)},
        app_scope="patient",
    )


@extend_schema(tags=["Payments - Offline to'lov"])
class OfflinePaymentViewSet(viewsets.GenericViewSet):
    """Offline (naqd) tarif to'lovi — bemor so'raydi, doctor tasdiqlaydi.

    - Bemor: `POST /payments/offline/` — tarifni naqd to'laganini bildiradi.
    - Doctor: `GET /payments/offline/?status=pending` — tasdiqlash kutayotganlar.
    - Doctor: `POST /payments/offline/{id}/confirm/` — tasdiqlaydi (komissiya balansdan).
    - Doctor: `POST /payments/offline/{id}/reject/` — rad etadi.
    """

    serializer_class = OfflinePaymentSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsPatient()]
        if self.action in ("confirm", "reject"):
            return [IsVerifiedDoctor()]
        return [IsAuthenticated()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return OfflinePayment.objects.none()
        user = self.request.user
        qs = OfflinePayment.objects.select_related(
            "doctor__user", "patient", "tariff", "purchase"
        )
        # Doctor scope → o'ziga kelganlar; aks holda bemor o'ziniki.
        if get_request_role(self.request) == User.Role.DOCTOR:
            profile = getattr(user, "doctor_profile", None)
            qs = qs.filter(doctor=profile) if profile else qs.none()
        else:
            qs = qs.filter(patient=user)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @extend_schema(
        summary="Offline to'lovlar ro'yxati",
        parameters=[
            OpenApiParameter("status", str, description="pending|confirmed|rejected")
        ],
        responses=OfflinePaymentSerializer(many=True),
    )
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        data = OfflinePaymentSerializer(
            qs, many=True, context={"request": request}
        ).data
        return Response({"count": len(data), "results": data})

    @extend_schema(
        responses={200: OfflinePaymentSerializer},
        summary="Bitta offline to'lov (status polling)",
    )
    def retrieve(self, request, *args, **kwargs):
        # Scoped queryset — bemor o'ziniki, doctor o'ziga kelganni ko'radi.
        return Response(
            OfflinePaymentSerializer(
                self.get_object(), context={"request": request}
            ).data
        )

    @extend_schema(
        request=OfflinePaymentCreateSerializer,
        responses={201: OfflinePaymentSerializer},
        summary="Offline to'lov so'rovi (bemor)",
    )
    def create(self, request, *args, **kwargs):
        serializer = OfflinePaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tariff = (
            DoctorTariff.objects.filter(
                id=serializer.validated_data["tariff_id"],
                status=DoctorTariff.Status.APPROVED,
                is_active=True,
            )
            .select_related("doctor__user")
            .first()
        )
        if not tariff:
            return Response({"detail": "Tarif topilmadi."}, status=404)

        # Allaqachon aktiv tarif bo'lsa — rad (already_active).
        if has_active_doctor_tariff(request.user, tariff.doctor):
            return Response(
                {
                    "detail": "Sizda ushbu doktorning faol tarifi mavjud.",
                    "code": "already_active",
                },
                status=400,
            )

        # Dublikat pending guard (DB constraint'dan oldin user-friendly xato).
        if OfflinePayment.objects.filter(
            patient=request.user,
            doctor=tariff.doctor,
            status=OfflinePayment.Status.PENDING,
        ).exists():
            return Response(
                {
                    "detail": "Sizda ushbu doktor uchun tasdiqlanmagan offline so'rov bor.",
                    "code": "duplicate_pending",
                },
                status=400,
            )

        amount = tariff.get_price_for(request.user)
        op = OfflinePayment.objects.create(
            patient=request.user,
            doctor=tariff.doctor,
            tariff=tariff,
            tariff_snapshot={
                "name": tariff.name,
                "price": str(tariff.price),
                "final_price": str(amount),
                "duration_days": tariff.duration_days,
                "features": tariff.features,
            },
            amount=amount,
        )

        _send_offline_notif(
            tariff.doctor.user,
            Notification.Type.OFFLINE_PAYMENT_REQUEST,
            {"uz": "Yangi offline to'lov", "ru": "Новый оффлайн-платёж", "cyr": "Янги офлайн тўлов"},
            {
                "uz": f"{request.user.full_name} naqd to'lovni tasdiqlashingizni so'ramoqda.",
                "ru": f"{request.user.full_name} просит подтвердить наличную оплату.",
                "cyr": f"{request.user.full_name} нақд тўловни тасдиқлашингизни сўрамоқда.",
            },
            {"kind": "offline_payment_request", "offline_payment_id": str(op.id)},
            app_scope="doctor",
        )

        return Response(
            OfflinePaymentSerializer(op, context={"request": request}).data,
            status=201,
        )

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description="Tasdiqlandi"),
            402: OpenApiResponse(description="Balans yetarli emas"),
            409: OpenApiResponse(description="Allaqachon ko'rib chiqilgan"),
        },
        summary="Offline to'lovni tasdiqlash (doctor)",
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        op = self.get_object()  # queryset doctor=profile bo'yicha scoped → begona uchun 404
        if op.status != OfflinePayment.Status.PENDING:
            return Response(
                {"detail": "Bu so'rov allaqachon ko'rib chiqilgan.", "code": "already_processed"},
                status=409,
            )

        # Edge-case: bemor shu orada online sotib oldi → auto-reject.
        if has_active_doctor_tariff(op.patient, op.doctor):
            op.status = OfflinePayment.Status.REJECTED
            op.rejection_reason = "Bemorda allaqachon faol tarif mavjud."
            op.confirmed_by = request.user
            op.processed_at = timezone.now()
            op.save(update_fields=["status", "rejection_reason", "confirmed_by", "processed_at"])
            _notify_offline_rejected(op)
            return Response(
                {
                    "detail": "Bemorda allaqachon faol tarif mavjud.",
                    "code": "already_active",
                    "id": op.id,
                    "status": op.status,
                },
                status=409,
            )

        commission_percent = resolve_commission(op.doctor)
        commission_amount = (op.amount * commission_percent / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        DoctorBalance.objects.get_or_create(doctor=op.doctor)

        with transaction.atomic():
            op_locked = (
                OfflinePayment.objects.select_for_update().filter(pk=op.pk).first()
            )
            if not op_locked or op_locked.status != OfflinePayment.Status.PENDING:
                return Response(
                    {"detail": "Bu so'rov allaqachon ko'rib chiqilgan.", "code": "already_processed"},
                    status=409,
                )
            balance = DoctorBalance.objects.select_for_update().get(doctor=op.doctor)
            if balance.balance < commission_amount:
                return Response(
                    {
                        "detail": "Komissiya uchun balans yetarli emas. Balansni to'ldiring.",
                        "code": "insufficient_balance",
                        "required": str(commission_amount),
                        "current": str(balance.balance),
                    },
                    status=402,
                )

            balance.charge_commission(commission_amount)

            now = timezone.now()
            tariff = op_locked.tariff
            duration_days = (
                tariff.duration_days
                if tariff
                else int((op_locked.tariff_snapshot or {}).get("duration_days") or 30)
            )
            purchase = DoctorTariffPurchase.objects.create(
                patient=op_locked.patient,
                doctor=op_locked.doctor,
                tariff=tariff,
                tariff_snapshot=op_locked.tariff_snapshot,
                starts_at=now,
                expires_at=now + timedelta(days=duration_days),
                amount_paid=op_locked.amount,
                commission_percent=commission_percent,
                commission_amount=commission_amount,
                doctor_earnings=op_locked.amount - commission_amount,
                payment=None,
                source=DoctorTariffPurchase.Source.OFFLINE,
                available_at=now,  # offline: balansда earnings yo'q → hold yo'q
            )
            op_locked.status = OfflinePayment.Status.CONFIRMED
            op_locked.commission_percent = commission_percent
            op_locked.commission_amount = commission_amount
            op_locked.purchase = purchase
            op_locked.confirmed_by = request.user
            op_locked.processed_at = now
            op_locked.save(update_fields=[
                "status", "commission_percent", "commission_amount",
                "purchase", "confirmed_by", "processed_at",
            ])

        balance.refresh_from_db()
        _send_offline_notif(
            op.patient,
            Notification.Type.OFFLINE_PAYMENT_CONFIRMED,
            {"uz": "To'lov tasdiqlandi", "ru": "Оплата подтверждена", "cyr": "Тўлов тасдиқланди"},
            {
                "uz": "Naqd to'lovingiz tasdiqlandi, tarif faollashtirildi.",
                "ru": "Ваша наличная оплата подтверждена, тариф активирован.",
                "cyr": "Нақд тўловингиз тасдиқланди, тариф фаоллаштирилди.",
            },
            {"kind": "offline_payment_confirmed", "offline_payment_id": str(op.id)},
            app_scope="patient",
        )

        return Response({
            "id": op.id,
            "status": OfflinePayment.Status.CONFIRMED,
            "commission_percent": str(commission_percent),
            "commission_amount": str(commission_amount),
            "balance_after": str(balance.balance),
            "purchase": {"id": purchase.id, "expires_at": purchase.expires_at},
        })

    @extend_schema(
        request=OfflineRejectSerializer,
        responses={200: OpenApiResponse(description="Rad etildi")},
        summary="Offline to'lovni rad etish (doctor)",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        op = self.get_object()
        if op.status != OfflinePayment.Status.PENDING:
            return Response(
                {"detail": "Bu so'rov allaqachon ko'rib chiqilgan.", "code": "already_processed"},
                status=409,
            )
        serializer = OfflineRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        op.status = OfflinePayment.Status.REJECTED
        op.rejection_reason = serializer.validated_data.get("reason", "")
        op.confirmed_by = request.user
        op.processed_at = timezone.now()
        op.save(update_fields=["status", "rejection_reason", "confirmed_by", "processed_at"])
        _notify_offline_rejected(op)
        return Response({
            "id": op.id,
            "status": op.status,
            "rejection_reason": op.rejection_reason,
        })


@extend_schema(tags=["Payments - Doctor"])
class DoctorTopupView(APIView):
    """Doctor balansini to'ldirish — provayder checkout URL qaytaradi."""

    permission_classes = [IsVerifiedDoctor]
    serializer_class = TopupRequestSerializer

    @extend_schema(
        request=TopupRequestSerializer,
        responses={200: OpenApiResponse(description="payment_id + checkout_url")},
        summary="Balansni to'ldirish (checkout)",
    )
    def post(self, request):
        serializer = TopupRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]
        provider_name = serializer.validated_data["provider"]

        min_amount = SystemSetting.get_decimal(
            TOPUP_MIN_AMOUNT_KEY, TOPUP_MIN_AMOUNT_DEFAULT
        )
        if amount < min_amount:
            return Response(
                {
                    "detail": f"Minimal summa {min_amount} so'm.",
                    "code": "min_amount",
                    "min": str(min_amount),
                },
                status=400,
            )

        try:
            provider = get_provider(provider_name)
        except ValueError as e:
            logger.warning("Topup: noto'g'ri provayder %s (%s)", provider_name, e)
            return Response(
                {"detail": "Noma'lum to'lov provayderi.", "code": "invalid_provider"},
                status=400,
            )

        profile, _ = DoctorProfile.objects.get_or_create(user=request.user)
        payment = build_topup_payment(request.user, profile, amount, provider_name)

        try:
            payment_url = provider.create_payment(payment)
        except Exception as exc:
            logger.exception(
                "Topup: checkout yaratishda xato doctor=%s payment=%s provider=%s err=%s",
                request.user.id, payment.id, provider_name, exc,
            )
            raise

        logger.info(
            "Topup invoice yaratildi: doctor=%s amount=%s provider=%s payment=%s",
            request.user.id, amount, provider_name, payment.id,
        )
        return Response({
            "payment_id": payment.id,
            "checkout_url": payment_url,
            "amount": str(amount),
            "provider": provider_name,
        })


# ============ Doctor cards (Kartalarim) ============


