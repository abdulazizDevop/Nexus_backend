from django.db.models import Avg, Count, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsPatient

from .models import REVIEW_EDIT_WINDOW_HOURS, Review, ReviewTag
from .serializers import (
    CRITICAL_MAX_RATING,
    POSITIVE_MIN_RATING,
    ReviewCreateSerializer,
    ReviewSerializer,
    ReviewTagSerializer,
    ReviewUpdateSerializer,
)
from .tasks import notify_doctor_new_review


@extend_schema(tags=["Feedbacks - Reviewlar"])
class ReviewViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Doctor reviewlari.

    Endpointlar:
        POST    /api/v1/feedbacks/reviews/                 — yangi review (Patient)
        GET     /api/v1/feedbacks/reviews/?doctor_id=N     — doctor reviewlari (paginated)
        GET     /api/v1/feedbacks/reviews/{id}/            — bittasi
        PATCH   /api/v1/feedbacks/reviews/{id}/            — tahrirlash (Patient, 24h ichida)
        DELETE  /api/v1/feedbacks/reviews/{id}/            — o'chirish (Patient, 24h ichida)
        GET     /api/v1/feedbacks/reviews/me/              — o'zining yozgan reviewlari (Patient)

    Qoidalar:
        - Faqat yakunlangan (status=completed) qabul uchun review yozish mumkin
        - Bir qabulga bitta review
        - Shu doctor uchun 30 kunda max 1 review (cooldown)
        - Patient yozilganidan 24 soat ichida tahrirlay yoki o'chira oladi
        - 24 soat o'tgach review qotib qoladi
    """

    queryset = Review.objects.none()
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head"]

    def get_serializer_class(self):
        if self.action == "create":
            return ReviewCreateSerializer
        if self.action in ("update", "partial_update"):
            return ReviewUpdateSerializer
        return ReviewSerializer

    def get_permissions(self):
        if self.action in ("create", "me", "update", "partial_update", "destroy"):
            return [IsPatient()]
        return [IsAuthenticated()]

    def _review_response(self, review: Review) -> ReviewSerializer:
        """Javob uchun ReviewSerializer'ni kontekst bilan qaytaradi."""
        return ReviewSerializer(review, context=self.get_serializer_context())

    def _ensure_owner_within_window(self, review: Review) -> None:
        if review.patient_id != self.request.user.id:
            raise PermissionDenied("Bu review siznikida emas.")
        if not review.edit_window_open:
            raise ValidationError(
                {
                    "detail": (
                        f"Review yozilgandan {REVIEW_EDIT_WINDOW_HOURS} soat o'tgan — "
                        "tahrirlash yoki o'chirish mumkin emas."
                    )
                }
            )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()

        qs = Review.objects.select_related(
            "patient", "doctor", "doctor__user"
        ).prefetch_related("tags")

        if self.action == "me":
            return qs.filter(patient=self.request.user)

        if self.action == "list":
            doctor_id = self.request.query_params.get("doctor_id")
            if doctor_id:
                qs = qs.filter(doctor_id=doctor_id)

            review_type = (self.request.query_params.get("type") or "all").lower()
            if review_type == "positive":
                qs = qs.filter(rating__gte=POSITIVE_MIN_RATING)
            elif review_type == "critical":
                qs = qs.filter(rating__lte=CRITICAL_MAX_RATING)

        return qs

    def _build_stats(self, base_qs):
        """Filterlardan qat'iy nazar — to'liq doctor reviewlariga qarab stats."""
        agg = base_qs.aggregate(
            average_rating=Avg("rating"),
            total=Count("id"),
            r5=Count("id", filter=Q(rating=5)),
            r4=Count("id", filter=Q(rating=4)),
            r3=Count("id", filter=Q(rating=3)),
            r2=Count("id", filter=Q(rating=2)),
            r1=Count("id", filter=Q(rating=1)),
            positive=Count("id", filter=Q(rating__gte=POSITIVE_MIN_RATING)),
            critical=Count("id", filter=Q(rating__lte=CRITICAL_MAX_RATING)),
        )
        avg = agg["average_rating"]
        total = agg["total"] or 0

        top_tags = []
        if total > 0:
            tag_rows = (
                ReviewTag.objects.filter(reviews__in=base_qs)
                .annotate(count=Count("reviews", filter=Q(reviews__in=base_qs)))
                .values("slug", "label_uz", "label_ru", "icon", "sentiment", "count")
                .order_by("-count")[:5]
            )
            for row in tag_rows:
                top_tags.append(
                    {
                        "slug": row["slug"],
                        "label_uz": row["label_uz"],
                        "label_ru": row["label_ru"],
                        "icon": row["icon"],
                        "sentiment": row["sentiment"],
                        "count": row["count"],
                        "percent": round(row["count"] * 100 / total),
                    }
                )

        return {
            "average_rating": round(avg, 1) if avg is not None else 0.0,
            "total_reviews": total,
            "rating_distribution": {
                "5": agg["r5"],
                "4": agg["r4"],
                "3": agg["r3"],
                "2": agg["r2"],
                "1": agg["r1"],
            },
            "filter_counts": {
                "all": total,
                "positive": agg["positive"],
                "critical": agg["critical"],
            },
            "top_tags": top_tags,
        }

    @extend_schema(
        summary="Doctor reviewlari ro'yxati + stats",
        description=(
            "Paginated reviewlar va statistika qaytaradi.\n\n"
            "**stats** (filter `type` ga bog'liq emas — har doim doctor bo'yicha to'liq):\n"
            "- `average_rating` — o'rtacha baho (1 xona aniqlikda)\n"
            "- `total_reviews` — jami sharhlar soni\n"
            "- `rating_distribution` — har bir yulduz bo'yicha taqsimot\n"
            "- `filter_counts` — `all` / `positive` / `critical` filterlar uchun sonlar\n\n"
            "**type filter:**\n"
            "- `all` (default) — hammasi\n"
            "- `positive` — Ijobiy (4-5 yulduz)\n"
            "- `critical` — Tanqidiy (1-3 yulduz)"
        ),
        parameters=[
            OpenApiParameter(
                "doctor_id",
                int,
                description="Aniq doctor reviewlarini olish (ixtiyoriy — bo'lmasa hammasi)",
            ),
            OpenApiParameter(
                "type",
                str,
                description="Filter: all | positive (4-5⭐) | critical (1-3⭐). Default: all",
                enum=["all", "positive", "critical"],
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())

        # Stats `type` filterga bog'liq emas — har doim doctor bo'yicha to'liq.
        doctor_id = request.query_params.get("doctor_id")
        stats_qs = Review.objects.all()
        if doctor_id:
            stats_qs = stats_qs.filter(doctor_id=doctor_id)
        stats = self._build_stats(stats_qs)

        page = self.paginate_queryset(qs)
        if page is not None:
            response = self.get_paginated_response(self.get_serializer(page, many=True).data)
            response.data["stats"] = stats
            return response

        return Response(
            {"results": self.get_serializer(qs, many=True).data, "stats": stats}
        )

    @extend_schema(summary="Bittasini ko'rish")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        request=ReviewCreateSerializer,
        responses=ReviewSerializer,
        summary="Yangi review yozish (Patient)",
        description=(
            "Faqat yakunlangan qabul (status=completed) uchun. "
            "Bir qabulga bitta review. "
            f"Yozilgandan {REVIEW_EDIT_WINDOW_HOURS} soat ichida tahrirlash/o'chirish mumkin. "
            "Shu doctor uchun keyingi review 30 kundan keyin yozilishi mumkin."
        ),
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        notify_doctor_new_review.delay(review.id)

        return Response(self._review_response(review).data, status=201)

    @extend_schema(
        request=ReviewUpdateSerializer,
        responses=ReviewSerializer,
        summary="Reviewni tahrirlash (Patient, 24 soat ichida)",
        description=(
            f"Patient o'z reviewini yozilganidan {REVIEW_EDIT_WINDOW_HOURS} soat ichida "
            "tahrirlay oladi. Faqat `rating` va `comment` o'zgartiriladi. "
            "Tahrirlanganidan so'ng `is_edited=true` bo'ladi."
        ),
    )
    def partial_update(self, request, *args, **kwargs):
        review = self.get_object()
        self._ensure_owner_within_window(review)

        serializer = ReviewUpdateSerializer(
            review,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        review = serializer.save(is_edited=True)
        return Response(self._review_response(review).data)

    @extend_schema(
        summary="Reviewni o'chirish (Patient, 24 soat ichida)",
        description=(
            f"Patient o'z reviewini yozilganidan {REVIEW_EDIT_WINDOW_HOURS} soat ichida "
            "o'chira oladi. 24 soat o'tgach o'chirib bo'lmaydi."
        ),
    )
    def destroy(self, request, *args, **kwargs):
        review = self.get_object()
        self._ensure_owner_within_window(review)
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Mening reviewlarim",
        description="Patient o'zi yozgan reviewlar ro'yxati.",
        responses=ReviewSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(qs, many=True).data)


@extend_schema(tags=["Feedbacks - Reviewlar"])
class ReviewTagViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Review uchun mavjud taglar.

    Endpoint: `GET /api/v1/feedbacks/tags/?sentiment=positive|negative`

    Frontend reviewdan oldin taglarni shu yerdan oladi va yulduz raytingiga
    qarab `positive` yoki `negative` filtr bilan ko'rsatadi.
    """

    queryset = ReviewTag.objects.none()
    serializer_class = ReviewTagSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ReviewTag.objects.none()

        qs = ReviewTag.objects.filter(is_active=True)
        sentiment = (self.request.query_params.get("sentiment") or "").lower()
        if sentiment in (ReviewTag.Sentiment.POSITIVE, ReviewTag.Sentiment.NEGATIVE):
            qs = qs.filter(sentiment=sentiment)
        return qs

    @extend_schema(
        summary="Taglar ro'yxati",
        description=(
            "Review yozayotgandagi tag tugmalari uchun.\n\n"
            "**sentiment filter:**\n"
            "- `positive` — yulduz ≥ 4 holatda\n"
            "- `negative` — yulduz ≤ 3 holatda\n"
            "- (yo'q) — barcha taglar"
        ),
        parameters=[
            OpenApiParameter(
                "sentiment",
                str,
                description="Filter: positive | negative",
                enum=["positive", "negative"],
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
