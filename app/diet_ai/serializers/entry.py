from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _image_url  # underscore helper (star bermaydi)

class ManualDietEntrySerializer(serializers.Serializer):
    """Patient qo'lda ovqat kiritish (kaloriya + macros)."""

    food_name = serializers.CharField(max_length=200)
    calories = serializers.IntegerField(min_value=1, max_value=10000)
    carbs_grams = serializers.IntegerField(min_value=0, max_value=1000, default=0)
    protein_grams = serializers.IntegerField(min_value=0, max_value=500, default=0)
    fat_grams = serializers.IntegerField(min_value=0, max_value=500, default=0)
    meal_type = serializers.ChoiceField(
        choices=DietEntry.MealType.choices, required=False, allow_null=True
    )
    date = serializers.DateField(
        required=False,
        help_text="Default: bugun",
    )

class DietEntrySerializer(serializers.ModelSerializer):
    """DietEntry o'qish uchun (history endpoint)."""

    source_display = serializers.CharField(source="get_source_display", read_only=True)
    meal_type_display = serializers.CharField(
        source="get_meal_type_display", read_only=True, default=None
    )
    image_url = serializers.SerializerMethodField()
    conversation_id = serializers.IntegerField(
        source="ai_message.conversation_id", read_only=True, default=None
    )
    patient_profile_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = DietEntry
        fields = [
            "id",
            "user",
            "patient_profile_id",
            "date",
            "food_name",
            "calories",
            "carbs_grams",
            "protein_grams",
            "fat_grams",
            "meal_type",
            "meal_type_display",
            "glycemic_load",
            "portion_grams",
            "ingredients",
            "source",
            "source_display",
            "ai_message",
            "conversation_id",
            "image_key",
            "image_url",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_image_url(self, obj):
        return _image_url(obj.image_key)

class IngredientEditItemSerializer(serializers.Serializer):
    """Bitta tahrirlangan ingredient (mobil faqat name + grams yuboradi)."""

    name = serializers.CharField(max_length=120)
    grams = serializers.IntegerField(min_value=1, max_value=5000)

class DietEntryIngredientsEditSerializer(serializers.Serializer):
    """PATCH /diet/history/{id}/ — ingredient ro'yxatini qayta yozish.

    Mavjud ingredient grammi o'zgarsa chiziqli scale; yangi ingredient AI orqali
    baholanadi; ro'yxatda yo'q ingredient tushib qoladi. Entry jami qayta hisoblanadi.
    """

    ingredients = IngredientEditItemSerializer(many=True, allow_empty=False)
