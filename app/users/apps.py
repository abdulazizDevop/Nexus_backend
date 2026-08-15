from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.users"

    def ready(self):
        # Signal handlers — User yaratilganda Patient avtomatik yaratiladi
        # (User.save() ichidagi mantiq'ga qo'shimcha qatlam — bulk_create
        # yoki migration orqali yaratilgan user'lar uchun ham ishlaydi).
        from app.users import signals  # noqa: F401
