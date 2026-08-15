import logging
import mimetypes

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import (
    BooleanField,
    Case,
    CharField,
    Count,
    F,
    Max,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from app.chat.tasks import (
    _send_call_cancel_push,
    check_missed_call,
    check_unreachable_call,
)
from app.doctors.models import DoctorPatient, DoctorProfile
from app.meetings.tasks import create_livekit_room
from app.notifications.models import DeviceToken, Notification
from app.notifications.catalog import render as render_notif
from app.notifications.tasks import (
    notify_by_key_user,
    send_push_to_user,
    send_voip_call_push,
)
from app.users.models import Patient
from core.permissions import IsAdmin, IsDoctorOrPatient, get_request_role, get_token_scope
from services.livekit import build_identity, create_room, create_token, generate_room_name
from services.storage import (
    generate_download_url,
    generate_file_key,
    generate_upload_url,
)

from ..models import CallSession, ChatRoom, Message
from ..utils import (
    enqueue_transcode_if_pending,
    get_last_seen,
    initial_audio_status,
    is_online,
    verify_chat_upload,
)
from ..serializers import (
    AdminChatRoomDetailSerializer,
    AdminChatRoomListSerializer,
    CallInitSerializer,
    CallSessionSerializer,
    ChatRoomCreateSerializer,
    ChatRoomDetailSerializer,
    ChatRoomListSerializer,
    MessageSerializer,
    UploadURLSerializer,
)

User = get_user_model()
logger = logging.getLogger("mediik.chat")

_BOOL_QS = {"true": True, "false": False}


def _other_participant_scope(room, sender_scope):
    """ChatRoom ichida boshqa ishtirokchining kutilgan scope'ini qaytaradi.

    Consultation room: agar sender 'patient' bo'lsa, callee 'doctor';
    aks holda — 'patient'. Boshqa hollarda None.
    """
    if room.room_type != ChatRoom.RoomType.CONSULTATION:
        return None
    if sender_scope == "patient":
        return "doctor"
    if sender_scope == "doctor":
        return "patient"
    return None


def _broadcast_ws(room_id, payload):
    """Channels group_send wrapper — Celery/Daphne yo'q bo'lsa silently skip."""
    try:
        async_to_sync(get_channel_layer().group_send)(f"chat_{room_id}", payload)
    except Exception:
        pass


def _is_admin_role(user):
    return user.role == User.Role.ADMIN


def unread_count_annotation(
    *, exclude_sender=None, exclude_admin=False, doctor_cutoff_user=None
):
    """O'qilmagan xabarlar Count annotatsiyasi (3 viewset uchun umumiy).

    System xabarlar ("Chat ochildi.", qo'ng'iroq loglari) hech qachon sanalmaydi —
    badge'ni noto'g'ri ko'tarib turardi. Qoidani bitta joyda saqlaymiz.

    `doctor_cutoff_user` berilsa: shu user DOCTOR bo'lgan room'larda
    `doctor_visible_from`'dan OLDINGI xabarlar sanalmaydi (marketplace AI thread
    doctor badge'ini ko'tarmasligi uchun). Bemor bo'lgan room'larda to'liq sanaladi.
    """
    flt = Q(messages__is_read=False, messages__is_deleted=False) & ~Q(
        messages__message_type=Message.MessageType.SYSTEM
    )
    if exclude_sender is not None:
        flt &= ~Q(messages__sender=exclude_sender)
    if exclude_admin:
        flt &= ~Q(messages__sender__role=User.Role.ADMIN)
    if doctor_cutoff_user is not None:
        # Xabar sanaladi agar: cutoff yo'q, YOKI men bu room doctor'i emasman
        # (bemor sifatida to'liq ko'raman), YOKI xabar cutoff'dan keyin.
        flt &= (
            Q(doctor_visible_from__isnull=True)
            | ~Q(doctor__user=doctor_cutoff_user)
            | Q(messages__created_at__gte=F("doctor_visible_from"))
        )
    return Count("messages", filter=flt)


def _support_last_sender_qs():
    """Support room'lar + oxirgi (system bo'lmagan) xabarning scope/role annotatsiyasi.

    'javob kutmoqda' — oxirgi xabar ADMIN scope'idan EMAS (bemor oxirgi yozgan,
    admin hali javob bermagan). is_read/mark_read'ga BOG'LIQ EMAS va ko'p rolli
    userlarni to'g'ri hisoblaydi (User.role emas — yuborilgan sender_scope).
    """
    last = (
        Message.objects.filter(room=OuterRef("pk"), is_deleted=False)
        .exclude(message_type=Message.MessageType.SYSTEM)
        .order_by("-created_at")
    )
    return ChatRoom.objects.filter(room_type=ChatRoom.RoomType.SUPPORT).annotate(
        last_scope=Subquery(last.values("sender_scope")[:1]),
        last_role=Subquery(last.values("sender__role")[:1]),
    )


def _is_awaiting_reply(last_scope, last_role) -> bool:
    by = last_scope or last_role
    return bool(by) and by != User.Role.ADMIN


class MessagePagination(CursorPagination):
    page_size = 50
    ordering = "-created_at"


class CallStartThrottle(UserRateThrottle):
    """Qo'ng'iroq boshlash uchun per-user rate limit (settings: call_start)."""

    scope = "call_start"


