from django.conf import settings
from django.db import models


class FeatureUsageDaily(models.Model):
    """Kunlik feature-foydalanish hisoblagichi (Phase 2 — deploydan keyingi data).

    Middleware har (user, feature, kun) uchun `count`ni oshiradi (atomic upsert).
    Tarixiy data `analytics.services` orqali mavjud yozuvlardan hisoblanadi;
    bu jadval deploydan keyingi ANIQ (endpoint-darajali) faollikni saqlaydi.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feature_usage",
    )
    feature = models.CharField(max_length=40, db_index=True)
    # app_scope (patient/doctor) — bitta phone ikki app'da; segmentatsiya uchun.
    scope = models.CharField(max_length=10, null=True, blank=True)
    date = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Feature usage (daily)"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature", "date"],
                name="uniq_feature_usage_user_feature_date",
            )
        ]
        indexes = [
            models.Index(fields=["feature", "date"]),
            models.Index(fields=["user", "-date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.feature}:{self.date}={self.count}"
