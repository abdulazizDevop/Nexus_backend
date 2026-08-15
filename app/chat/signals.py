from django.db.models.signals import post_save
from django.dispatch import receiver

from app.chat.models import ChatRoom, Message
from app.meetings.models import Appointment


@receiver(post_save, sender=Appointment)
def create_chat_room_on_approval(sender, instance, **kwargs):
    """Appointment tasdiqlanganda agar mavjud bo'lmasa unikal chat ochadi."""
    if instance.status != Appointment.Status.APPROVED:
        return

    # XAVFSIZLIK/BUG: get_or_create_consultation patient_profile + doctor_profile
    # bilan ishlatamiz — FK lar to'g'ri set bo'ladi va UniqueConstraint ishlaydi.
    # Legacy get_or_create_for_users User-darajada xona yaratib, dublikat xona +
    # push misrouting keltirib chiqarardi (view get_or_create_consultation bilan
    # ikkinchi xona ochib yuborardi).
    if not instance.patient_profile:
        return

    room, created = ChatRoom.get_or_create_consultation(
        instance.patient_profile, instance.doctor
    )

    if created:
        Message.create_system(
            room,
            "Chat ochildi.",
            sender=instance.doctor.user,
            scope="doctor",
        )
