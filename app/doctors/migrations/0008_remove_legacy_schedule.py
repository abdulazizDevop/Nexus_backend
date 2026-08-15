"""Eski DoctorSchedule va BlockedSlot modellarini olib tashlash.

Spec §10 step 10: data migration o'tgandan keyin eski jadvallarni butunlay
o'chirish. Yangi `Slot` modeli ikkalasining ham vazifasini bajaradi.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("doctors", "0007_migrate_schedule_to_slots"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="doctorschedule",
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name="doctorschedule",
            name="doctor",
        ),
        migrations.DeleteModel(
            name="BlockedSlot",
        ),
        migrations.DeleteModel(
            name="DoctorSchedule",
        ),
    ]
