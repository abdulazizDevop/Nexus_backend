"""User-bog'liq signal'lar.

Defense-in-depth: User.save() ichida Patient avtomatik yaratiladi, lekin
bulk_create() yoki Migration RunPython orqali User yaratilsa save()
chaqirilmaydi. Shu sababli post_save signal — qo'shimcha qatlam.
"""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from app.users.models import Patient

User = get_user_model()


@receiver(post_save, sender=User)
def ensure_patient_profile(sender, instance, created, **kwargs):
    """Har User uchun Patient profile borligini ta'minlaydi."""
    if not created:
        return
    Patient.objects.get_or_create(user=instance)
