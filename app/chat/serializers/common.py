from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import ChatRoom, Message
from services.storage import generate_download_url


def _latest_message(room):
    """Xonadagi oxirgi o'chirilmagan xabar (yoki None). Query mantiqi bir joyda.

    View `latest_messages` (to_attr) prefetch qilgan bo'lsa — keshdan o'qiydi
    (rooms list N+1 oldini olish); aks holda bitta query (detail va h.k.)."""
    cached = getattr(room, "latest_messages", None)
    if cached is not None:
        return cached[0] if cached else None
    return room.messages.filter(is_deleted=False).order_by("-created_at").first()
