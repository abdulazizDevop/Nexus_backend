"""active_role=doctor bo'lib, referral_code=NULL bo'lgan user'larga kod beradi.

Yangi mantiq User.save() ichida active_role=doctor uchun ham kod
generatsiya qiladi. Bu migration shu o'zgarishdan oldin yaratilgan
(eski) user'larga kodni backfill qilish uchun bir martalik.
"""

import uuid

from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("users", "User")
    qs = User.objects.filter(active_role="doctor", referral_code__isnull=True)

    used = set(
        User.objects.exclude(referral_code__isnull=True).values_list("referral_code", flat=True)
    )
    for user in qs.iterator():
        while True:
            code = uuid.uuid4().hex[:8].upper()
            if code not in used:
                used.add(code)
                break
        user.referral_code = code
        user.save(update_fields=["referral_code"])


def revert(apps, schema_editor):
    pass  # revert kerak emas — kod berilgan bo'lsa, qoldiriladi


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_accountdeletionrequest"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_code=revert),
    ]
