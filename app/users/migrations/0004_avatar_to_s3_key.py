from django.db import migrations, models


def clear_avatars(apps, schema_editor):
    """Mavjud lokal avatar yo'llarini tozalash — endi S3 key formatida saqlanadi.

    Sabab: ImageField (lokal) → CharField (DO Spaces key) ga o'tish.
    Eski lokal fayllar bekor qilingan, userlar qaytadan yuklashlari kerak.
    """
    User = apps.get_model("users", "User")
    User.objects.exclude(avatar="").update(avatar=None)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_set_active_role"),
    ]

    operations = [
        # 1-qadam: eski qiymatlarni tozalash
        migrations.RunPython(clear_avatars, migrations.RunPython.noop),
        # 2-qadam: ImageField → CharField
        migrations.AlterField(
            model_name="user",
            name="avatar",
            field=models.CharField(
                blank=True,
                help_text=(
                    "DO Spaces key (masalan: 'avatars/5/abc123.jpg'). "
                    "To'liq URL serializer'da generate_download_url orqali yaratiladi."
                ),
                max_length=500,
                null=True,
            ),
        ),
    ]
