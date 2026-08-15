from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar


@extend_schema(tags=["Diet AI - Patient"])
class DietTipTodayView(APIView):
    """Kunlik AI tavsiyasi — bitta qisqa jumla.

    Redis'da 24 soat cachelanadi (har user uchun bir marta generatsiya qilinadi kuniga).
    """

    permission_classes = [IsPatient]

    @extend_schema(
        summary="Bugun uchun AI tavsiyasi",
        description=(
            "Gemini bemor profili, bugungi entries va doctor cheklovlari asosida "
            "bitta qisqa amaliy maslahat beradi. Kunlik cache (24h) — token tejash."
        ),
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        today = timezone.localdate()
        lang = get_request_lang(request)
        cache_key = f"diet_tip:{request.user.id}:{today.isoformat()}:{lang}"
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        user_context = services.build_user_context(request.user)
        summary = services.get_daily_summary(request.user, today)

        today_entries = DietEntry.objects.filter(
            user=request.user, date=today
        ).order_by("-created_at")[:10]
        entries_text = (
            "\n".join(
                f"- {e.food_name}: {e.calories} kcal, {e.carbs_grams}g uglevod, "
                f"{e.protein_grams}g oqsil, {e.fat_grams}g yog'"
                for e in today_entries
            )
            or "- (bugun hech narsa yozilmagan)"
        )

        cal = summary["calories"]
        limits_line = (
            f"Chegara: {cal['limit']} kcal, iste'mol: {cal['consumed']} kcal "
            f"({cal['percent']}%)"
            if cal["limit"]
            else f"Bugungi iste'mol: {cal['consumed']} kcal (chegara belgilanmagan)"
        )

        prompt = (
            f"Bemor profili:\n{user_context}\n\n"
            f"{limits_line}\n\n"
            f"Bugungi ovqatlar:\n{entries_text}\n\n"
            "Shu asosida bitta qisqa, amaliy maslahat bering (1-2 jumla, 150 belgidan "
            "oshmasin). Professional bo'l. 'Quyidagi:' yoki 'Tavsiya:' kabi so'zlar "
            "kerak emas, to'g'ridan-to'g'ri maslahat jumlasi bo'lsin."
        )

        lang_name = {"uz": "o'zbek", "ru": "rus", "cyr": "o'zbek (kirill yozuvida)"}.get(
            lang, "o'zbek"
        )
        system_prompt = (
            "Siz parhez bo'yicha AI maslahatchisiz. Faqat bitta qisqa amaliy maslahat "
            f"bering (1-2 jumla). Tibbiy diagnoz qo'ymang. Javobni {lang_name} tilida yozing."
        )
        result = generate_text(prompt=prompt, system_instruction=system_prompt)

        if "error" in result:
            return Response(
                {"detail": result["error"]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        response_data = {
            "tip": (result["text"] or "").strip(),
            "generated_at": timezone.now().isoformat(),
            "tokens_used": result.get("tokens_input", 0) + result.get("tokens_output", 0),
        }

        # 24 soatga cache (kunlik TTL)
        cache.set(cache_key, response_data, timeout=60 * 60 * 24)
        return Response(response_data)


@extend_schema(tags=["Diet AI - Patient"])
class DietMyRestrictionsView(APIView):
    """Bemor o'z parhez cheklovlarini ko'rish."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=DietRestrictionSerializer(many=True),
        summary="Mening parhez cheklovlarim",
    )
    def get(self, request):
        qs = DietRestriction.objects.filter(
            patient=request.user, is_active=True
        ).select_related("doctor")
        return Response(DietRestrictionSerializer(qs, many=True).data)


# --- DOCTOR ---


