from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_callsession_ringing_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="audio_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Transcode kutilmoqda"),
                    ("ready", "Tayyor"),
                    ("failed", "Xato"),
                ],
                help_text="Ovozli xabar transcode holati (web webm→m4a). Audio bo'lmasa null.",
                max_length=10,
                null=True,
            ),
        ),
    ]
