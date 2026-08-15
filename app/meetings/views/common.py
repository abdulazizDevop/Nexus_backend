from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from app.doctors.models import Slot
from app.meetings.tasks import (
    create_livekit_room,
    send_review_request_notification,
)
from app.notifications.models import Notification
from app.notifications.tasks import (
    notify_by_key_user,
    send_push_to_user,
)
from core.permissions import (
    IsAdmin,
    IsDoctor,
    IsPatient,
    IsVerifiedDoctor,
    get_token_scope,
)
from services.livekit import build_identity, create_room, create_token, generate_room_name
from services.storage import generate_download_url

from ..models import Appointment
from ..serializers import (
    AppointmentApproveSerializer,
    AppointmentCancelSerializer,
    AppointmentCreateSerializer,
    AppointmentDetailSerializer,
    AppointmentListSerializer,
    AppointmentRejectSerializer,
)


class CallStartThrottle(UserRateThrottle):
    """start-call (push/ring) uchun per-user rate limit (settings: call_start).

    Push-spam (harassment, batareya tugatish) oldini oladi — chat moduli bilan
    bir xil 10/min cheklov.
    """

    scope = "call_start"


def _release_slot(appointment):
    """Appointment cancelled/rejected — bog'langan slot bo'lsa, free qaytaramiz.

    `transaction.atomic()` ichida chaqirilishi kutiladi (caller'da).
    select_for_update bilan konkurent o'zgartirishlardan himoyalanadi.
    """
    slot = Slot.objects.select_for_update().filter(appointment=appointment).first()
    if slot:
        slot.status = Slot.Status.FREE
        slot.appointment = None
        slot.reason = ""
        slot.save(update_fields=["status", "appointment", "reason", "updated_at"])


def _require_status(appointment, expected, message):
    """Appointment status `expected` (status yoki status'lar to'plami) ichida
    bo'lmasa 400 Response qaytaradi, aks holda None.

    `expected` bitta Status qiymati yoki ularning iterable'i bo'lishi mumkin.
    """
    allowed = expected if isinstance(expected, (tuple, list, set)) else (expected,)
    if appointment.status not in allowed:
        return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)
    return None


def _validate_call_ready(appointment):
    """LiveKit ulanishidan oldin appointment holatini tekshiradi."""
    if appointment.status != Appointment.Status.APPROVED:
        return Response(
            {"detail": "Faqat tasdiqlangan uchrashuvga qo'shilish mumkin."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if appointment.meeting_type != Appointment.MeetingType.ONLINE:
        return Response(
            {"detail": "Bu offline uchrashuv — video call mavjud emas."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not appointment.room_name:
        return Response(
            {"detail": "Room hali yaratilmagan."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


def _build_livekit_token(appointment, request, default_scope: str):
    """Joriy user uchun LiveKit kirish tokenini yaratadi."""
    name = request.user.full_name or ""
    if default_scope == "doctor" and name:
        name = f"Dr. {name}"
    return create_token(
        room_name=appointment.room_name,
        participant_name=name or str(request.user.id),
        participant_identity=build_identity(
            request.user.id, get_token_scope(request) or default_scope
        ),
        # Room approve bosqichida yaratiladi — call paytida yaratish kerak emas
        # (minimal-privilege; room_create grant'i resurs abuse vektori).
        allow_create=False,
    )


def _call_response(appointment, token):
    """Mobile mijozga qaytariladigan LiveKit ulanish payload'i."""
    return Response(
        {
            "token": token,
            "room_name": appointment.room_name,
            "livekit_url": settings.LIVEKIT_URL,
        }
    )


def _send_meeting_started_push(
    appointment, caller_user, callee_user_id, callee_scope, caller_label
):
    """Rejalashtirilgan meeting boshlanganda callee'ga oddiy banner push yuboradi.

    Zoom/Meet pattern — CallKit chiqmaydi, FCM banner notification.
    `callee_scope` — patient/doctor app'ning aynan biriga yo'naltirish uchun
    (bitta phone'da ikkala app login bo'lishi mumkin).
    """
    caller_avatar = ""
    if caller_user.avatar:
        try:
            caller_avatar = generate_download_url(caller_user.avatar) or ""
        except Exception:
            caller_avatar = ""

    send_push_to_user.delay(
        callee_user_id,
        "Uchrashuv boshlandi",
        f"{caller_label} sizni meeting'da kutmoqda",
        {
            "type": "meeting_started",
            "meeting_id": str(appointment.id),
            "caller_id": str(caller_user.id),
            "caller_name": caller_label,
            "caller_avatar_url": caller_avatar,
            "room_name": appointment.room_name,
            "meeting_type": appointment.meeting_type,
        },
        data_only=False,
        app_scope=callee_scope,
    )


def _initiate_call(
    appointment,
    request,
    *,
    caller_scope,
    callee_user_id,
    callee_scope,
    caller_label,
    send_push,
):
    """start-call / accept-call / join-call uchun umumiy yo'l.

    Validatsiya → LiveKit token → (xohlasa) 30s dedupe bilan callee'ga push →
    LiveKit ulanish payload'i. Patient/Doctor viewset'lar faqat
    callee/scope/label ni hisoblab shu helper'ni chaqiradi.
    """
    err = _validate_call_ready(appointment)
    if err:
        return err

    token = _build_livekit_token(appointment, request, default_scope=caller_scope)

    if send_push and callee_user_id:
        dedupe_key = f"meeting_push:{appointment.id}:{callee_user_id}"
        if not cache.get(dedupe_key):
            cache.set(dedupe_key, True, timeout=30)
            try:
                _send_meeting_started_push(
                    appointment=appointment,
                    caller_user=request.user,
                    callee_user_id=callee_user_id,
                    callee_scope=callee_scope,
                    caller_label=caller_label,
                )
            except Exception:
                pass

    return _call_response(appointment, token)


def _safe_notify(**kwargs):
    """Notification yuborish — Redis o'chgan bo'lsa appointment'ni partlatmasin."""
    try:
        notify_by_key_user.delay(**kwargs)
    except Exception:
        pass


# --- Patient tomonidan ---
