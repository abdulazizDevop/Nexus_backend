from django.db import migrations, models


def clear_certificate_images(apps, schema_editor):
    """Mavjud lokal certificate image yo'llarini tozalash.

    ImageField (lokal) → CharField (DO Spaces key) ga o'tish.
    """
    DoctorCertificate = apps.get_model("doctors", "DoctorCertificate")
    DoctorCertificate.objects.exclude(image="").update(image=None)


class Migration(migrations.Migration):

    dependencies = [
        ("doctors", "0003_doctorpatient"),
    ]

    operations = [
        migrations.RunPython(clear_certificate_images, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="doctorcertificate",
            name="image",
            field=models.CharField(
                blank=True,
                help_text="DO Spaces key (masalan: 'certificates/5/abc123.jpg')",
                max_length=500,
                null=True,
            ),
        ),
    ]
