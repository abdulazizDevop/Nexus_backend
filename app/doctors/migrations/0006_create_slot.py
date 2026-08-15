"""Slot modelini yaratish (eski jadvallarga tegmaydi).

Spec §10 step 1: Slot table'ni yarat — `(doctor_id, date, start_time)` UNIQUE bilan.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("doctors", "0005_doctorpatient_requested_by_and_more"),
        ("meetings", "0002_appointment_cancelled_by"),
    ]

    operations = [
        migrations.CreateModel(
            name="Slot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("date", models.DateField()),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("free", "Bo'sh"),
                            ("booked", "Bron qilingan"),
                            ("blocked", "Yopilgan"),
                        ],
                        default="free",
                        max_length=10,
                    ),
                ),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "appointment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="slot",
                        to="meetings.appointment",
                    ),
                ),
                (
                    "doctor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="slots",
                        to="doctors.doctorprofile",
                    ),
                ),
            ],
            options={
                "ordering": ["date", "start_time"],
            },
        ),
        migrations.AddIndex(
            model_name="slot",
            index=models.Index(
                fields=["doctor", "date"], name="doctors_slo_doctor__a81488_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="slot",
            index=models.Index(
                fields=["doctor", "date", "status"],
                name="doctors_slo_doctor__73e9e5_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="slot",
            constraint=models.UniqueConstraint(
                fields=("doctor", "date", "start_time"),
                name="uniq_slot_doctor_date_start",
            ),
        ),
    ]
