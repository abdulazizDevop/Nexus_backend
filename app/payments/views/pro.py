from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


@extend_schema(tags=["Payments - Pro (Patient)"])
class ProPlansView(APIView):
    """Aktiv Pro planlar ro'yxati + features (patient)"""

    permission_classes = [IsAuthenticated]
    serializer_class = ProPlanPublicSerializer

    @extend_schema(
        summary="Pro planlar ro'yxati",
        responses=ProPlanPublicSerializer(many=True),
    )
    def get(self, request):
        plans = ProPlan.objects.filter(is_active=True).order_by(
            "order", "duration_days"
        )
        return Response(ProPlanPublicSerializer(plans, many=True).data)


@extend_schema(tags=["Payments - Pro (Patient)"])
class MyProSubscriptionView(APIView):
    """O'z aktiv obunam"""

    permission_classes = [IsAuthenticated]
    serializer_class = MyProStatusSerializer

    @extend_schema(
        summary="Mening Pro obunam",
        responses=MyProStatusSerializer,
    )
    def get(self, request):

        sub = get_active_pro_subscription(request.user)
        if not sub:
            return Response({"is_active": False, "subscription": None})
        return Response(
            {
                "is_active": True,
                "subscription": ProSubscriptionSerializer(sub).data,
            }
        )


@extend_schema(tags=["Payments - Pro (Patient)"])
class ProSubscribeView(APIView):
    """Pro obunaga yozilish — invoice URL qaytaradi"""

    permission_classes = [IsPatient]

    @extend_schema(
        request=SubscribeRequestSerializer,
        responses={
            200: InvoiceResponseSerializer,
            409: OpenApiResponse(description="Aktiv Pro obuna mavjud"),
        },
        summary="Pro obunaga yozilish",
    )
    def post(self, request):
        serializer = SubscribeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)


        active_sub = get_active_pro_subscription(request.user)
        if active_sub:
            return Response(
                {
                    "detail": "Sizda allaqachon aktiv Pro obuna mavjud. "
                    "Yangi obuna sotib olish uchun joriy obuna tugashini kuting.",
                    "expires_at": active_sub.expires_at,
                },
                status=409,
            )

        plan = ProPlan.objects.filter(
            id=serializer.validated_data["plan_id"], is_active=True
        ).first()
        if not plan:
            return Response({"detail": "Plan topilmadi."}, status=404)

        provider_name = serializer.validated_data["provider"]
        try:
            provider = get_provider(provider_name)
        except ValueError as e:
            # Exception matnini klientga qaytarmaymiz (info leak) — server'da log.
            logger.warning("Noto'g'ri to'lov provayderi: %s (%s)", provider_name, e)
            return Response({"detail": "Noma'lum to'lov provayderi."}, status=400)

        payment = build_pro_payment(request.user, plan, provider_name)

        try:
            payment_url = provider.create_payment(payment)
        except Exception as exc:
            logger.exception(
                "Pro subscribe: payment_url yaratishda xato user=%s plan=%s provider=%s payment=%s err=%s",
                request.user.id, plan.id, provider_name, payment.id, exc,
            )
            raise

        logger.info(
            "Pro subscribe invoice yaratildi: user=%s plan=%s(%s) amount=%s provider=%s payment=%s url=%s",
            request.user.id,
            plan.id,
            plan.name,
            plan.price,
            provider_name,
            payment.id,
            payment_url,
        )

        return Response(
            {
                "payment_id": payment.id,
                "payment_url": payment_url,
                "amount": plan.price,
                "provider": provider_name,
            }
        )


# ============ Doctor tariflari (Patient) ============


