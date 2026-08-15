from .common import *  # noqa: F401,F403


def _validate_tags_for_rating(slugs, rating):
    """Tag sentiment'i rating bilan mos kelishini tekshiradi.

    Tekshiradi:
    - Hamma slug DB'da mavjud va is_active
    - Tag sentiment rating'ga mos: rating ≥ 4 → positive, ≤ 3 → negative

    Returns:
        list[ReviewTag] — resolved tag obyektlari
    Raises:
        serializers.ValidationError — slug yo'q yoki sentiment mos kelmasa
    """
    expected_sentiment = ReviewTag.sentiment_for_rating(rating)

    tags = list(ReviewTag.objects.filter(slug__in=slugs, is_active=True))
    found_slugs = {t.slug for t in tags}
    missing = set(slugs) - found_slugs
    if missing:
        raise serializers.ValidationError(
            {"tag_slugs": f"Topilmagan taglar: {sorted(missing)}"}
        )

    wrong = [t.slug for t in tags if t.sentiment != expected_sentiment]
    if wrong:
        raise serializers.ValidationError(
            {
                "tag_slugs": (
                    f"Rating {rating} bilan {expected_sentiment} taglar tanlanishi kerak. "
                    f"Mos kelmaydi: {wrong}"
                )
            }
        )

    return tags


class ReviewCreateSerializer(serializers.ModelSerializer):
    """Patient yangi review yaratadi.

    Request:
        {
            "appointment_id": 12,
            "rating": 5,
            "tag_slugs": ["explains_well", "attentive", "recommend"],
            "comment": "Ajoyib shifokor!"   # ixtiyoriy
        }
    """

    appointment_id = serializers.PrimaryKeyRelatedField(
        queryset=Appointment.objects.all(),
        source="appointment",
        write_only=True,
    )
    tag_slugs = serializers.ListField(
        child=serializers.SlugField(),
        required=False,
        allow_empty=True,
        write_only=True,
        help_text=(
            "Tanlangan taglar slug ro'yxati. Ratingga mos sentiment'da bo'lishi kerak: "
            "rating ≥ 4 → faqat positive, rating ≤ 3 → faqat negative."
        ),
    )

    class Meta:
        model = Review
        fields = ["appointment_id", "rating", "comment", "tag_slugs"]

    def validate(self, attrs):
        slugs = attrs.get("tag_slugs") or []
        if slugs:
            attrs["_resolved_tags"] = _validate_tags_for_rating(slugs, attrs["rating"])
        return attrs

    def create(self, validated_data):
        validated_data.pop("tag_slugs", None)
        tags = validated_data.pop("_resolved_tags", [])
        request = self.context["request"]
        appointment = validated_data["appointment"]

        # TOCTOU himoyasi: validate_appointment_id'dagi cooldown tekshiruvi va
        # bu yerdagi create atomik emas — parallel ikki so'rov (har xil
        # appointment'lar bilan) cooldown'ni aylanib o'tishi mumkin. Shu doctor
        # bo'yicha oxirgi review'ni qulflab qayta tekshiramiz.
        with transaction.atomic():
            cooldown_start = timezone.now() - timedelta(days=REVIEW_COOLDOWN_DAYS)
            recent = (
                Review.objects.select_for_update()
                .filter(
                    patient=request.user,
                    doctor=appointment.doctor,
                    created_at__gte=cooldown_start,
                )
                .order_by("-created_at")
                .first()
            )
            if recent:
                days_left = max(
                    1,
                    REVIEW_COOLDOWN_DAYS - (timezone.now() - recent.created_at).days,
                )
                raise serializers.ValidationError(
                    f"Shu doctor uchun yaqinda review qoldirgansiz. "
                    f"Keyingi review {days_left} kundan keyin yozish mumkin."
                )

            review = super().create(validated_data)
            if tags:
                review.tags.set(tags)
        return review

    def validate_appointment_id(self, appointment):
        request = self.context["request"]

        if appointment.patient_id != request.user.id:
            raise serializers.ValidationError(
                "Bu qabul siznikida emas — boshqa bemornikiga review yoza olmaysiz."
            )

        if appointment.status != Appointment.Status.COMPLETED:
            raise serializers.ValidationError(
                "Faqat yakunlangan qabul uchun review qoldira olasiz."
            )

        if Review.objects.filter(appointment=appointment).exists():
            raise serializers.ValidationError(
                "Bu qabul uchun review allaqachon yozilgan — review o'zgartirib bo'lmaydi."
            )

        cooldown_start = timezone.now() - timedelta(days=REVIEW_COOLDOWN_DAYS)
        recent = (
            Review.objects.filter(
                patient=request.user,
                doctor=appointment.doctor,
                created_at__gte=cooldown_start,
            )
            .order_by("-created_at")
            .first()
        )
        if recent:
            days_left = max(
                1,
                REVIEW_COOLDOWN_DAYS - (timezone.now() - recent.created_at).days,
            )
            raise serializers.ValidationError(
                f"Shu doctor uchun yaqinda review qoldirgansiz. "
                f"Keyingi review {days_left} kundan keyin yozish mumkin."
            )

        return appointment


class ReviewUpdateSerializer(serializers.ModelSerializer):
    """Patient o'z reviewini 24 soat ichida tahrirlaydi.

    `rating`, `comment` va `tag_slugs` o'zgartirilishi mumkin.
    `tag_slugs` jo'natilsa — taglar to'liq almashtiriladi (yangilari bilan).
    Yuborilmasa — taglar o'z holicha qoladi.
    """

    tag_slugs = serializers.ListField(
        child=serializers.SlugField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    class Meta:
        model = Review
        fields = ["rating", "comment", "tag_slugs"]

    def validate(self, attrs):
        slugs = attrs.get("tag_slugs")
        if slugs is None:
            return attrs
        rating = attrs.get("rating") or self.instance.rating
        attrs["_resolved_tags"] = _validate_tags_for_rating(slugs, rating)
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop("tag_slugs", None)
        tags = validated_data.pop("_resolved_tags", None)
        instance = super().update(instance, validated_data)
        if tags is not None:
            instance.tags.set(tags)
        return instance
