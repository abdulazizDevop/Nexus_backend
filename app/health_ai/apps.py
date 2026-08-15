from django.apps import AppConfig


class HealthAiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.health_ai"
    label = "health_ai"
    verbose_name = "Health AI (doctor report + doctor chat)"
