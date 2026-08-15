from .common import *  # noqa: F401,F403 - header importlar + helperlar

class DietRestrictionSerializer(serializers.ModelSerializer):
    """Doctor cheklovi (CRUD)."""

    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    doctor_name = serializers.CharField(
        source="doctor.full_name", read_only=True, default=None
    )
    patient_profile_id = serializers.IntegerField(read_only=True)
    doctor_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DietRestriction
        fields = [
            "id",
            "patient",
            "patient_profile_id",
            "doctor_profile_id",
            "patient_name",
            "doctor",
            "doctor_name",
            "rule",
            "reason",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "patient_profile_id",
            "doctor_profile_id",
            "patient_name",
            "doctor_name",
            "doctor",
            "created_at",
            "updated_at",
        ]

class DietProfileSerializer(serializers.ModelSerializer):
    """Diet profil o'qish — antropometriya/jins/yosh yagona manbadan (User/MedicalCard) merge."""

    goal_display = serializers.CharField(source="get_goal_display", read_only=True)
    gender = serializers.SerializerMethodField()
    birth_date = serializers.SerializerMethodField()
    birth_year = serializers.SerializerMethodField()
    height_cm = serializers.SerializerMethodField()
    weight_kg = serializers.SerializerMethodField()
    conditions = serializers.SerializerMethodField()

    class Meta:
        model = DietProfile
        fields = [
            "goal",
            "goal_display",
            "target_weight_kg",
            "pace_kg_week",
            "activity_level",
            "meals_per_day",
            "restrictions",
            "obstacles",
            "outcomes",
            "target_overrides",
            "motivation",
            "gender",
            "birth_date",
            "birth_year",
            "height_cm",
            "weight_kg",
            "conditions",
            "created_at",
            "updated_at",
        ]

    def get_gender(self, obj):
        return obj.user.sex or None

    def get_birth_date(self, obj):
        return obj.user.birth_date.isoformat() if obj.user.birth_date else None

    def get_birth_year(self, obj):
        return obj.user.birth_date.year if obj.user.birth_date else None

    def _card(self, obj):
        from app.medical.models import MedicalCard

        return MedicalCard.objects.filter(user_id=obj.user_id).first()

    def get_height_cm(self, obj):
        card = self._card(obj)
        return card.height_cm if card else None

    def get_weight_kg(self, obj):
        card = self._card(obj)
        return card.weight_kg if card else None

    def get_conditions(self, obj):
        """Med-kartadaги kasalliklar (yagona manba, §8.4) — o'qish uchun merge."""
        from app.medical.models import MedicalCondition

        return [
            {"type": c.type, "name": c.name, "severity": c.severity or None}
            for c in MedicalCondition.objects.filter(user_id=obj.user_id).order_by(
                "-created_at"
            )[:20]
        ]

class DietProfileWriteSerializer(serializers.Serializer):
    """PUT /diet/profile/ — profil + antropometriya (med-kartaga) + jins/yosh (User'ga)."""

    goal = serializers.ChoiceField(choices=DietProfile.Goal.choices, required=False)
    target_weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True
    )
    pace_kg_week = serializers.DecimalField(
        max_digits=3, decimal_places=2, required=False, allow_null=True
    )
    activity_level = serializers.ChoiceField(
        choices=DietProfile.Activity.choices, required=False
    )
    meals_per_day = serializers.ChoiceField(choices=DietProfile.Meals.choices, required=False)
    restrictions = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )
    obstacles = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )
    outcomes = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )
    target_overrides = serializers.DictField(required=False)
    motivation = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    # Yagona manba maydonlari (backend boshqa modelga yozadi):
    height_cm = serializers.IntegerField(
        min_value=100, max_value=250, required=False, allow_null=True
    )
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=1, min_value=20, max_value=400,
        required=False, allow_null=True,
    )
    gender = serializers.ChoiceField(choices=["male", "female"], required=False)
    # Yosh — to'liq sana (ustun) yoki faqat yil (backward-compat)
    birth_date = serializers.DateField(required=False, allow_null=True)
    birth_year = serializers.IntegerField(min_value=1900, max_value=2100, required=False)

    def validate_target_overrides(self, value):
        allowed = {"calories", "carbs_g", "protein_g", "fat_g"}
        return {
            k: v for k, v in (value or {}).items() if k in allowed and v is not None
        }

class DietTargetPerMealSerializer(serializers.Serializer):
    meal_type = serializers.CharField()
    calories = serializers.IntegerField()

class DietTargetsSerializer(serializers.Serializer):
    source = serializers.CharField()
    calories = serializers.IntegerField()
    carbs_g = serializers.IntegerField()
    protein_g = serializers.IntegerField()
    fat_g = serializers.IntegerField()
    per_meal = DietTargetPerMealSerializer(many=True)
    explanation = serializers.CharField()
    warning = serializers.CharField(allow_null=True)
