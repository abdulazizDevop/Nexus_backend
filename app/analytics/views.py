from django.core.cache import cache
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsSuperOrSimpleAdmin

from . import services

_VALID_PERIODS = {"7d", "30d", "90d", "365d", "all"}


def _period(request):
    p = request.query_params.get("period", "30d")
    return p if p in _VALID_PERIODS else "30d"


@extend_schema(exclude=True)
class AnalyticsOverviewView(APIView):
    """Umumiy foydalanish dashboard'i — feature counts, kategoriya, heatmap, top userlar.

    Og'ir agregatsiya (barcha feature bo'ylab) — 10 daqiqa cache qilinadi.
    """

    permission_classes = [IsSuperOrSimpleAdmin]

    def get(self, request):
        period = _period(request)
        cache_key = f"analytics:overview:{period}"
        data = cache.get(cache_key)
        if data is None:
            data = services.overview(period)
            cache.set(cache_key, data, 600)
        return Response(data)


@extend_schema(exclude=True)
class AnalyticsTimeseriesView(APIView):
    """Bitta feature — kunlik count (grafik)."""

    permission_classes = [IsSuperOrSimpleAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter("feature", str, description="registry feature key"),
            OpenApiParameter("period", str, description="7d|30d|90d|365d|all"),
        ]
    )
    def get(self, request):
        feature = request.query_params.get("feature", "")
        return Response(services.timeseries(feature, _period(request)))


@extend_schema(exclude=True)
class AnalyticsInactiveView(APIView):
    """Churn — `days` kundan beri jim turgan (ishlatmay qo'ygan) userlar."""

    permission_classes = [IsSuperOrSimpleAdmin]

    def get(self, request):
        try:
            days = int(request.query_params.get("days", 30))
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))
        return Response(services.inactive_users(days=days))


@extend_schema(exclude=True)
class AnalyticsUserUsageView(APIView):
    """Bitta user — feature bo'yicha foydalanishi + kunlik timeline + segment."""

    permission_classes = [IsSuperOrSimpleAdmin]

    def get(self, request, user_id=None):
        return Response(services.user_usage(user_id, _period(request)))
