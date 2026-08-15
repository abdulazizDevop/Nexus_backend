from django.apps import AppConfig


class ChatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.chat"

    def ready(self):
        import app.chat.signals  # noqa: F401
