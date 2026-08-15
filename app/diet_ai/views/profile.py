from .common import *  # noqa: F401,F403 - umumiy importlar + services + konstantalar
from .common import _parse_query_date


@extend_schema(tags=["Diet AI - Patient"])
class DietUsageView(APIView):
    """Bugungi limit holati."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=DailyUsageSerializer, summary="Bugungi limit")
    def get(self, request):
        info = services.check_daily_limit(request.user)
        info["is_pro"] = info["limit"] is None
        return Response(info)


@extend_schema(tags=["Diet AI - Patient"])
class DietProfileView(APIView):
    """Parhez profili — onboarding/tahrirlash. Antropometriya med-kartaga,
    jins/yosh User'ga yoziladi (yagona manba)."""

    permission_classes = [IsPatient]

    @extend_schema(responses=DietProfileSerializer, summary="Diet profil (404 = onboarding)")
    def get(self, request):
        profile = DietProfile.objects.filter(user=request.user).first()
        if not profile:
            return Response(
                {"detail": "no_profile", "message": "Parhez profili yo'q"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(DietProfileSerializer(profile).data)

    @extend_schema(
        request=DietProfileWriteSerializer,
        responses=DietProfileSerializer,
        summary="Diet profil yaratish/yangilash",
    )
    def put(self, request):
        ser = DietProfileWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        with transaction.atomic():
            # 1) DietProfil (faqat maqsad/turmush tarzi maydonlari)
            profile_fields = {
                k: v
                for k, v in data.items()
                if k in (
                    "goal", "target_weight_kg", "pace_kg_week",
                    "activity_level", "meals_per_day", "restrictions",
                    "obstacles", "outcomes", "target_overrides", "motivation",
                )
            }
            DietProfile.objects.update_or_create(
                user=request.user, defaults=profile_fields
            )

            # 2) Antropometriya → MedicalCard (yagona manba)
            if "height_cm" in data or "weight_kg" in data:
                from app.medical.models import MedicalCard

                card, _ = MedicalCard.objects.get_or_create(user=request.user)
                weight_changed = False
                if data.get("height_cm") is not None:
                    card.height_cm = data["height_cm"]
                if data.get("weight_kg") is not None and card.weight_kg != data["weight_kg"]:
                    card.weight_kg = data["weight_kg"]
                    weight_changed = True
                card.updated_by = request.user
                card.save()
                if weight_changed:
                    services.record_weight(request.user, data["weight_kg"])

            # 3) Jins/yosh → User (wizard ustun — berilsa HAR DOIM yangilanadi)
            u = request.user
            user_fields = []
            if data.get("gender"):
                u.sex = data["gender"]
                user_fields.append("sex")
            if data.get("birth_date"):
                u.birth_date = data["birth_date"]  # to'liq ISO sana (ustun)
                user_fields.append("birth_date")
            elif data.get("birth_year") and not u.birth_date:
                u.birth_date = date_cls(data["birth_year"], 1, 1)  # fallback
                user_fields.append("birth_date")
            if user_fields:
                u.save(update_fields=user_fields)

        # Profil o'zgardi — tip-today keshi eskirdi (3 til)
        today_iso = date_cls.today().isoformat()
        cache.delete_many(
            [f"diet_tip:{request.user.id}:{today_iso}:{lg}" for lg in ("uz", "ru", "cyr")]
        )

        profile = DietProfile.objects.get(user=request.user)
        return Response(DietProfileSerializer(profile).data)


@extend_schema(tags=["Diet AI - Patient"])
class DietTargetsView(APIView):
    """Kunlik target (kaloriya + makro + har-mahal). Ustunlik: doctor > auto > default."""

    permission_classes = [IsPatient]

    @extend_schema(responses=DietTargetsSerializer, summary="Kunlik target")
    def get(self, request):
        target_date, err = _parse_query_date(request)
        if err:
            return err
        target_date = target_date or date_cls.today()
        targets = services.resolve_targets(request.user, target_date)
        return Response(DietTargetsSerializer(targets).data)


@extend_schema(tags=["Diet AI - Patient"])
class DietProgressView(APIView):
    """Haftalik parhez progressi (Pro) — vazn dinamikasi + o'rtacha kaloriya + streak."""

    permission_classes = [IsPatient]

    @extend_schema(responses=OpenApiTypes.OBJECT, summary="Haftalik progress (Pro)")
    def get(self, request):
        if not services.has_diet_pro_feature(request.user, "diet_weekly_report"):
            return Response(
                {
                    "detail": "pro_required",
                    "feature": "diet_weekly_report",
                    "message": "Haftalik AI progress — Pro imkoniyati.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            weeks = int(request.query_params.get("weeks", 4))
        except (TypeError, ValueError):
            weeks = 4
        return Response(services.get_diet_progress(request.user, weeks))


