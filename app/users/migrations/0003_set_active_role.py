"""Mavjud userlarga active_role = role o'rnatish."""
from django.db import migrations


def set_active_role(apps, schema_editor):
    User = apps.get_model("users", "User")
    for user in User.objects.all():
        user.active_role = user.role
        user.save(update_fields=["active_role"])


def revert(apps, schema_editor):
    pass  # revert kerak emas


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_user_active_role"),
    ]

    operations = [
        migrations.RunPython(set_active_role, reverse_code=revert),
    ]
