from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar
from .common import _filter_diet_history_qs,_parse_query_date


@extend_schema(tags=["Diet AI - Patient"])
class DietHistoryView(APIView):
    """Patient parhez tarixi (DietEntry ro'yxati)."""

    permission_classes = [IsPatient]

    @extend_schema(
        responses=DietEntrySerializer(many=True),
        summary="Parhez tarixi",
        description=(
            "Query params: ?date=2026-04-20 (bitta kun), yoki ?from=...&to=... (oraliq). "
            "Parametr berilmasa: oxirgi 30 kun."
        ),
    )
    def get(self, request):
        qs = _filter_diet_history_qs(
            DietEntry.objects.filter(user=request.user).select_related("ai_message"),
            request,
        )
        return Response(DietEntrySerializer(qs, many=True).data)


@extend_schema(tags=["Diet AI - Patient"])
class DietEntryDeleteView(APIView):
    """Patient DietEntry'ni o'chiradi (HealthIndicator'dan ayiradi)."""

    permission_classes = [IsPatient]

    @extend_schema(
        summary="Parhez yozuvini o'chirish",
        description=(
            "DietEntry o'chiriladi + kaloriya/uglevod/oqsil/yog' indicator qiymatidan "
            "ayiriladi (atomic). Ayirganda 0 dan past tushmaydi."
        ),
        responses={204: None},
    )
    def delete(self, request, entry_id=None):
        try:
            entry = DietEntry.objects.get(id=entry_id, user=request.user)
        except DietEntry.DoesNotExist:
            return Response(
                {"detail": "Yozuv topilmadi yoki sizga tegishli emas."},
                status=status.HTTP_404_NOT_FOUND,
            )

        with transaction.atomic():
            services.remove_diet_entry_indicators(entry.id)
            entry.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=DietEntryIngredientsEditSerializer,
        responses=DietEntrySerializer,
        summary="Parhez yozuvi ingredientlarini tahrirlash",
        description=(
            "Ingredient ro'yxatini qayta yozadi va entry jamini + kunlik "
            "indicator'larni moslashtiradi (atomic).\n\n"
            "Qoidalar:\n"
            "- Mavjud ingredient grammi o'zgarsa → chiziqli scale (AI'siz).\n"
            "- Ro'yxatda yo'q ingredient → yig'indidan tushadi.\n"
            "- Yangi ingredient → AI per-100g baholaydi. Tanimasa 400 "
            "{'detail': 'unknown_ingredient', 'name': '...'}.\n"
            "- Entry calories/carbs/protein/fat = ingredientlar yig'indisi.\n"
            "- glycemic_load va meal_advice qayta hisoblanmaydi.\n"
            "Faqat yozuv egasi (bemor) tahrirlay oladi."
        ),
    )
    def patch(self, request, entry_id=None):
        try:
            entry = DietEntry.objects.get(id=entry_id, user=request.user)
        except DietEntry.DoesNotExist:
            return Response(
                {"detail": "Yozuv topilmadi yoki sizga tegishli emas."},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = DietEntryIngredientsEditSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_list = ser.validated_data["ingredients"]

        # AI mini-call (yangi ingredient) lock'dan TASHQARIDA — DB lock'ni
        # sekin AI so'roviga bog'lab qo'ymaslik uchun avval hisoblaymiz.
        try:
            new_ingredients, totals = services.recalc_ingredients(entry, new_list)
        except services.UnknownIngredient as exc:
            return Response(
                {"detail": "unknown_ingredient", "name": exc.name},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Eski indicator event'larni tozalab, yangisini yozamiz (event-source).
            services.remove_diet_entry_indicators(entry.id)
            entry.ingredients = new_ingredients
            entry.calories = totals["calories"]
            entry.carbs_grams = totals["carbs_grams"]
            entry.protein_grams = totals["protein_grams"]
            entry.fat_grams = totals["fat_grams"]
            entry.save(update_fields=[
                "ingredients", "calories", "carbs_grams",
                "protein_grams", "fat_grams",
            ])
            services.add_to_daily_indicators(
                user=request.user,
                date=entry.date,
                calories=entry.calories,
                carbs=entry.carbs_grams,
                protein=entry.protein_grams,
                fat=entry.fat_grams,
                diet_entry_id=entry.id,
            )

        return Response(DietEntrySerializer(entry).data)


@extend_schema(tags=["Diet AI - Patient"])
class DietDailySummaryView(APIView):
    """Bugungi (yoki berilgan sana) kaloriya + macros xulosasi."""

    permission_classes = [IsPatient]

    @extend_schema(
        summary="Kunlik parhez xulosasi",
        description=(
            "Query: ?date=2026-04-20 (default: bugun). "
            "4 ta indicator bo'yicha consumed/limit/remaining/over_limit/percent qaytariladi. "
            "Umumiy status: on_track | near_limit | over."
        ),
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        target_date, err = _parse_query_date(request)
        if err:
            return err
        if target_date is None:
            target_date = timezone.localdate()

        return Response(services.get_daily_summary(request.user, target_date))


