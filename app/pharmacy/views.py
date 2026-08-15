import os
import tempfile

from django.db.models import Count
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
)
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app.pharmacy.importer import import_drugs_from_xls
from app.pharmacy.models import Drug, DrugImportLog
from app.pharmacy.search import normalize_for_search
from app.pharmacy.serializers import (
    DrugImportLogSerializer,
    DrugImportUploadSerializer,
    DrugSerializer,
)
from core.permissions import IsSuperOrSimpleAdmin


_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}

# Import logda saqlanadigan maksimal xato soni va import_logs ro'yxati limiti.
MAX_STORED_ERRORS = 50
IMPORT_LOG_LIST_LIMIT = 50


def _parse_bool(raw: str | None):
    """Query param boolean parsing — None, True, False qaytaradi."""
    if raw is None:
        return None
    lower = raw.lower()
    if lower in _TRUE_VALUES:
        return True
    if lower in _FALSE_VALUES:
        return False
    return None


@extend_schema(tags=["Pharmacy"])
class DrugViewSet(viewsets.ModelViewSet):
    """Dorilar va tibbiy buyumlar katalogi.

    - **List/Detail** — har autentifikatsiyalangan foydalanuvchi uchun ochiq
      (mobile app'da qidiruv va doctor muolaja yozayotganda)
    - **Create/Update/Delete/Import** — faqat super yoki simple admin
    """

    queryset = Drug.objects.none()
    serializer_class = DrugSerializer
    parser_classes = [MultiPartParser, JSONParser]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [IsSuperOrSimpleAdmin()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Drug.objects.none()

        qs = Drug.objects.all()

        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(name_normalized__icontains=normalize_for_search(search))

        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        is_active = _parse_bool(self.request.query_params.get("is_active"))
        if is_active is not None:
            qs = qs.filter(is_active=is_active)

        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)

        return qs

    @extend_schema(
        summary="Dorilar ro'yxati",
        parameters=[
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Nom bo'yicha qidiruv (Kirill va Lotin ikkalasi ham mos keladi)",
            ),
            OpenApiParameter(
                "category",
                OpenApiTypes.STR,
                description="Kategoriya filtri: drug | substance | in_vivo | med_device | in_vitro",
            ),
            OpenApiParameter(
                "is_active",
                OpenApiTypes.BOOL,
                description="Faqat aktiv yoki annulirovannye",
            ),
            OpenApiParameter(
                "source",
                OpenApiTypes.STR,
                description="manual | import",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(summary="Bitta dori tafsiloti")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(summary="Qo'lda dori qo'shish (admin)")
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(summary="Dorini yangilash (admin)")
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @extend_schema(summary="Dorini qisman yangilash (admin)")
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Dorini o'chirish (admin)")
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Admin qo'lda qo'shsa, source=manual."""
        serializer.save(source=Drug.Source.MANUAL)

    # ---- Import ----

    @extend_schema(
        request=DrugImportUploadSerializer,
        responses=DrugImportLogSerializer,
        summary="Excel'dan import (admin)",
        description=(
            "Sog'liqni saqlash vazirligi nashr etgan .xls fayldan dorilarni import "
            "qiladi. `(category, name)` unique — mavjudlari yangilanadi (idempotent)."
        ),
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_excel(self, request):
        serializer = DrugImportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        category = serializer.validated_data["category"]
        is_active = serializer.validated_data["is_active"]

        # xlrd file-like obyektni qabul qilmaydi — tempfile orqali path beramiz.
        with tempfile.NamedTemporaryFile(suffix=".xls", delete=False) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        try:
            try:
                result = import_drugs_from_xls(
                    tmp_path, category=category, is_active=is_active
                )
            except ImportError:
                return Response(
                    {"detail": "xlrd paketi server'da o'rnatilmagan."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            except Exception:
                return Response(
                    {
                        "detail": (
                            "Faylni o'qib bo'lmadi. .xls formatda ekanligiga "
                            "ishonch hosil qiling."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        log = DrugImportLog.objects.create(
            filename=uploaded_file.name,
            category=category,
            uploaded_by=request.user if request.user.is_authenticated else None,
            total_rows=result["total"],
            created_count=result["created"],
            updated_count=result["updated"],
            skipped_count=result["skipped"],
            error_count=len(result["errors"]),
            errors=result["errors"][:MAX_STORED_ERRORS],
            is_active_default=is_active,
        )
        return Response(
            DrugImportLogSerializer(log).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses=DrugImportLogSerializer(many=True),
        summary="Import tarixi (admin)",
    )
    @action(detail=False, methods=["get"], url_path="import-logs")
    def import_logs(self, request):
        logs = DrugImportLog.objects.all()[:IMPORT_LOG_LIST_LIMIT]
        return Response(DrugImportLogSerializer(logs, many=True).data)

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string"},
                                "label": {"type": "string"},
                                "count": {"type": "integer"},
                            },
                        },
                    },
                    "total": {"type": "integer"},
                    "active_total": {"type": "integer"},
                    "inactive_total": {"type": "integer"},
                },
            }
        },
        summary="Statistika (admin paneldagi kartalar uchun)",
    )
    @action(detail=False, methods=["get"], url_path="stats")
    def stats(self, request):
        cat_counts = dict(
            Drug.objects.values("category")
            .annotate(c=Count("id"))
            .values_list("category", "c")
        )

        categories = [
            {
                "value": value,
                "label": label,
                "count": cat_counts.get(value, 0),
            }
            for value, label in Drug.Category.choices
        ]
        total = sum(c["count"] for c in categories)
        active_total = Drug.objects.filter(is_active=True).count()
        inactive_total = total - active_total

        return Response(
            {
                "categories": categories,
                "total": total,
                "active_total": active_total,
                "inactive_total": inactive_total,
            }
        )
