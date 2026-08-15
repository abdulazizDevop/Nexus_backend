from django.urls import path

from .views import (
    AnalyticsInactiveView,
    AnalyticsOverviewView,
    AnalyticsTimeseriesView,
    AnalyticsUserUsageView,
)

urlpatterns = [
    path("admin/analytics/overview/", AnalyticsOverviewView.as_view(), name="analytics-overview"),
    path("admin/analytics/timeseries/", AnalyticsTimeseriesView.as_view(), name="analytics-timeseries"),
    path("admin/analytics/inactive/", AnalyticsInactiveView.as_view(), name="analytics-inactive"),
    path(
        "admin/analytics/user/<int:user_id>/",
        AnalyticsUserUsageView.as_view(),
        name="analytics-user-usage",
    ),
]
