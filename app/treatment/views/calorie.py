from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _notify_patient_calorie, _validate_doctor_patient_link  # underscore helper (star bermaydi)

@extend_schema(tags=["Kaloriya"])
class DailyCalorieLimitViewSet(viewsets.ViewSet):
    """Kunlik kaloriya chegarasi — Doctor belgilaydi, Patient o'zinikini o'qiydi"""

    permission_classes = [IsVerifiedDoctor]

    def get_permissions(self):
        # my_limit — har qanday autentifikatsiya qilingan user (patient o'zinikini oladi)
        if self.action == "my_limit":
            return [IsAuthenticated()]
        return [IsVerifiedDoctor()]

    def get_serializer_class(self):
        if self.action == "set_limit":
            return DailyCalorieLimitSetSerializer
        return DailyCalorieLimitSerializer

    @extend_schema(
        request=DailyCalorieLimitSetSerializer,
        responses=DailyCalorieLimitSerializer,
        summary="Bemorga kunlik kaloriya belgilash",
        description="Doctor bemorga kunlik kaloriya chegarasi belgilaydi. Agar oldin belgilangan bo'lsa yangilanadi.",
    )
    @action(detail=False, methods=["post"], url_path="set")
    def set_limit(self, request):
        serializer = DailyCalorieLimitSetSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        patient = get_object_or_404(User, id=serializer.validated_data["patient_id"])

        limit, _ = DailyCalorieLimit.objects.update_or_create(
            patient=patient,
            defaults={
                "calories": serializer.validated_data["calories"],
                "carbs_limit": serializer.validated_data.get("carbs_limit"),
                "protein_limit": serializer.validated_data.get("protein_limit"),
                "fat_limit": serializer.validated_data.get("fat_limit"),
                "set_by": request.user,
                "notes": serializer.validated_data.get("notes", ""),
            },
        )

        _notify_patient_calorie(patient, cleared=False)
        return Response(DailyCalorieLimitSerializer(limit).data)

    @extend_schema(
        summary="Bemor kaloriya normasini olib tashlash (doctor)",
        responses={204: None},
        description="Doctor belgilagan normani o'chiradi. Bemorga push yuboriladi.",
    )
    @action(detail=False, methods=["delete"], url_path="clear")
    def clear_limit(self, request):
        patient_id = request.query_params.get("patient_id") or request.data.get("patient_id")
        patient = get_object_or_404(User, id=patient_id)
        # Doctor↔patient ACCEPTED bog'lanish tekshiruvi (set bilan bir xil qoida)
        from app.doctors.models import DoctorPatient

        linked = DoctorPatient.objects.filter(
            doctor__user=request.user,
            patient=patient,
            status=DoctorPatient.Status.ACCEPTED,
        ).exists()
        if not linked:
            return Response(
                {"detail": "Bu bemor sizga biriktirilmagan."},
                status=status.HTTP_403_FORBIDDEN,
            )
        deleted, _ = DailyCalorieLimit.objects.filter(patient=patient).delete()
        if deleted:
            _notify_patient_calorie(patient, cleared=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Mening kunlik kaloriya + macros chegaram (patient)",
        description=(
            "Patient o'ziga doctor belgilagan kunlik kaloriya + macros chegaralarini oladi. "
            "Query: ?date=2026-04-20 (default: bugun). "
            "Chegara belgilanmagan bo'lsa: limits=null, set_by=null. "
            "Istalgan kun uchun consumed/remaining summary qaytariladi."
        ),
    )
    @action(detail=False, methods=["get"], url_path="my-limit")
    def my_limit(self, request):
        # Inline import — circular dependency oldini olish (diet_ai → treatment)
        from app.diet_ai.services import get_daily_summary

        date_str = request.query_params.get("date")
        if date_str:
            try:
                target_date = date_cls.fromisoformat(date_str)
            except ValueError:
                return Response(
                    {"detail": "Noto'g'ri sana formati. YYYY-MM-DD ishlating."},
                    status=400,
                )
        else:
            target_date = timezone.localdate()

        limit_obj = (
            DailyCalorieLimit.objects.select_related("set_by")
            .filter(patient=request.user)
            .first()
        )
        summary = get_daily_summary(request.user, target_date)

        return Response(
            {
                "date": target_date.isoformat(),
                "limits": {
                    "calories": limit_obj.calories if limit_obj else None,
                    "carbs_limit": limit_obj.carbs_limit if limit_obj else None,
                    "protein_limit": limit_obj.protein_limit if limit_obj else None,
                    "fat_limit": limit_obj.fat_limit if limit_obj else None,
                },
                "summary": summary,
                "set_by": (
                    {
                        "id": limit_obj.set_by.id,
                        "full_name": limit_obj.set_by.full_name,
                        "phone": limit_obj.set_by.phone,
                    }
                    if limit_obj and limit_obj.set_by
                    else None
                ),
                "notes": limit_obj.notes if limit_obj else "",
                "updated_at": (
                    limit_obj.updated_at.isoformat() if limit_obj else None
                ),
            }
        )

    @extend_schema(
        summary="Bemor kaloriya chegarasini ko'rish",
        description="patient_id query param bilan bemorning kaloriya chegarasini ko'rish.",
    )
    @action(detail=False, methods=["get"], url_path="get")
    def get_limit(self, request):
        patient_id = request.query_params.get("patient_id")
        if not patient_id:
            return Response(
                {"detail": "patient_id query parameter kerak."},
                status=400,
            )

        # XAVFSIZLIK: doctor↔patient ACCEPTED bog'lanish tekshiruvi — aks holda
        # istalgan doctor istalgan bemorning kaloriya chegarasi/ismini o'qiy oladi
        # (IDOR). set_limit'dagi bir xil tekshiruv. ValidationError → DRF 400.
        _validate_doctor_patient_link(patient_id, {"request": request})

        try:
            limit = DailyCalorieLimit.objects.select_related("patient", "set_by").get(
                patient_id=patient_id
            )
        except DailyCalorieLimit.DoesNotExist:
            return Response(
                {"detail": "Kaloriya chegarasi belgilanmagan."},
                status=404,
            )

        return Response(DailyCalorieLimitSerializer(limit).data)
