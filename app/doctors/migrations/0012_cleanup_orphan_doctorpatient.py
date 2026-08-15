"""Eski soft-delete'dan qolgan orfan DoctorPatient qatorlarini tozalash.

`_soft_delete_user` boshlanishida DoctorPatient'larni o'chirishni qo'shgan
(commit ed82e39), lekin undan oldin delete-account qilingan userlarning
qatorlari DB'da qoldi. Natijada bemor ro'yxatlarida "deleted_<id>_<hex>"
nomli doctor ko'rinib qolgan edi.
"""

from django.db import migrations


def cleanup(apps, schema_editor):
    DoctorPatient = apps.get_model("doctors", "DoctorPatient")
    deleted, _ = DoctorPatient.objects.filter(
        doctor__user__is_active=False
    ).delete()
    deleted_p, _ = DoctorPatient.objects.filter(
        patient__is_active=False
    ).delete()
    print(f"  → Orfan DoctorPatient (deleted doctor): {deleted}")
    print(f"  → Orfan DoctorPatient (deleted patient): {deleted_p}")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("doctors", "0011_alter_specialty_options_alter_specialty_name"),
    ]
    operations = [migrations.RunPython(cleanup, noop_reverse)]
