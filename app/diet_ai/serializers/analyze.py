from .common import *  # noqa: F401,F403 - header importlar + helperlar

class AnalyzePhotoSerializer(serializers.Serializer):
    """Ovqat rasmini tahlil qilish.

    Mobile flow:
        1. POST /diet/upload-url/ → S3 presigned URL olinadi
        2. PUT {upload_url} → fayl S3 ga yuklanadi
        3. POST /diet/analyze-photo/ {image_key, conversation_id, ...} yuboriladi
    """

    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    image_key = serializers.CharField(max_length=500)
    food_name = serializers.CharField(required=False, allow_blank=True, default="")
    portion = serializers.CharField(required=False, allow_blank=True, default="")
    grams = serializers.IntegerField(required=False, allow_null=True)
    pieces = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")

class AnalyzeTextSerializer(serializers.Serializer):
    """Ovqatni MATN orqali tahlil qilish — analyze-photo'ning rasmsiz egizagi.

    Farqi: image_key YO'Q, food_name MAJBURIY. meal_type ixtiyoriy — berilsa
    assistant metadata'ga yoziladi va confirm-calories entry yaratganda ishlatiladi.
    """

    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    food_name = serializers.CharField(max_length=200)
    grams = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=5000
    )
    portion = serializers.CharField(required=False, allow_blank=True, default="")
    pieces = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=100
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    meal_type = serializers.ChoiceField(
        choices=DietEntry.MealType.choices, required=False, allow_null=True
    )

class PhotoUploadUrlSerializer(serializers.Serializer):
    """Ovqat rasmi uchun presigned URL so'rovi."""

    file_name = serializers.CharField(default="meal.jpg")
    file_type = serializers.CharField(default="image/jpeg")

    def validate_file_type(self, value):
        allowed = ("image/jpeg", "image/png", "image/webp")
        if value not in allowed:
            raise serializers.ValidationError(
                f"Faqat {', '.join(allowed)} ruxsat etilgan"
            )
        return value

class DailyUsageSerializer(serializers.Serializer):
    """Bugungi limit holati."""

    allowed = serializers.BooleanField()
    used = serializers.IntegerField()
    limit = serializers.IntegerField(allow_null=True, help_text="None = cheksiz (Pro)")
    remaining = serializers.IntegerField(allow_null=True)
    is_pro = serializers.BooleanField()

class ConfirmCaloriesSerializer(serializers.Serializer):
    """AI tahlilidagi kaloriyani kunlik hisobga qo'shish."""

    calories = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=10000,
        help_text=(
            "Qo'shiladigan kaloriya (kcal). Agar yuborilmasa, "
            "AI estimated_calories ishlatiladi."
        ),
    )
    meal_type = serializers.ChoiceField(
        choices=DietEntry.MealType.choices, required=False, allow_null=True
    )

class _DailyIndicatorStatSerializer(serializers.Serializer):
    consumed = serializers.IntegerField()
    limit = serializers.IntegerField(allow_null=True)
    remaining = serializers.IntegerField(allow_null=True)
    over_limit = serializers.BooleanField()
    percent = serializers.IntegerField(allow_null=True)

class _AddedAmountsSerializer(serializers.Serializer):
    calories = serializers.IntegerField()
    carbs_grams = serializers.IntegerField()
    protein_grams = serializers.IntegerField()
    fat_grams = serializers.IntegerField()

class _DailySummaryInlineSerializer(serializers.Serializer):
    date = serializers.CharField()
    calories = _DailyIndicatorStatSerializer()
    carbs = _DailyIndicatorStatSerializer()
    protein = _DailyIndicatorStatSerializer()
    fat = _DailyIndicatorStatSerializer()
    entries_count = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["on_track", "near_limit", "over"])

class ConfirmCaloriesResponseSerializer(serializers.Serializer):
    """Confirm qilingandan keyin qaytadigan javob."""

    confirmed = serializers.BooleanField()
    entry_id = serializers.IntegerField()
    added = _AddedAmountsSerializer()
    today = _DailySummaryInlineSerializer()
    warning = serializers.CharField(allow_null=True)
