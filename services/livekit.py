"""LiveKit integratsiya — video call uchun room va token boshqarish.

Flow:
1. Doctor appointment ni approve qilganda → Celery task orqali room yaratiladi
2. Patient yoki Doctor /join-call/ qilganda → token qaytadi
3. Token bilan LiveKit ga ulanadi (mobile SDK orqali)

Room yaratish async (Celery) — Django view bloklanmaydi.
Token yaratish sinxron — faqat JWT sign, tez.

IDENTITY:
LiveKit'da bir xil `identity` ikki marta connect qilolmaydi — eski connection
kicked. Yandex Taxi modelida bir xil User ham patient, ham doctor bo'lishi
mumkin. Shuning uchun identity tarkibiga scope va session marker qo'shamiz:
    "{user_id}_{scope}_{session_hex}"
"""

import asyncio
import logging
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from livekit.api import AccessToken, CreateRoomRequest, LiveKitAPI, VideoGrants

logger = logging.getLogger(__name__)


def generate_room_name() -> str:
    """Unique room name yaratadi."""
    return f"mediik-{uuid.uuid4().hex[:12]}"


def build_identity(user_id: int | str, scope: str | None = None) -> str:
    """LiveKit uchun unique identity yaratadi.

    `{user_id}_{scope}_{6_hex}` formatida — har create_token chaqiruvi unique.
    Bir user multi-device, multi-scope da bir vaqtda LiveKit'da bo'la oladi
    (har device alohida connect bo'ladi, identity collision yo'q).
    """
    scope_part = scope or "user"
    session_marker = secrets.token_hex(3)  # 6 hex chars
    return f"{user_id}_{scope_part}_{session_marker}"


async def _create_room_async(room_name: str) -> bool:
    async with LiveKitAPI(
        url=settings.LIVEKIT_URL,
        api_key=settings.LIVEKIT_API_KEY,
        api_secret=settings.LIVEKIT_API_SECRET,
    ) as api:
        await api.room.create_room(
            CreateRoomRequest(
                name=room_name,
                empty_timeout=600,
                max_participants=2,
            )
        )
    logger.info("LiveKit room yaratildi: %s", room_name)
    return True


def create_room(room_name: str) -> bool:
    """Celery worker ichidan chaqiriladi — worker sinxron, asyncio.run() xavfsiz."""
    return asyncio.run(_create_room_async(room_name))


def create_token(
    room_name: str,
    participant_name: str,
    participant_identity: str,
    allow_create: bool = False,
) -> str:
    """LiveKit ga ulanish uchun JWT token yaratadi (sinxron, network yo'q).

    XAVFSIZLIK: default `allow_create=False` — token faqat NOMLANGAN room'ga
    ulana oladi, ixtiyoriy room yarata olmaydi (room_create grant'i resurs
    abuse vektori). Room oldindan yaratilmagan kam holatdagina explicit True
    bering (masalan chat room hali tayyor bo'lmaganda).
    TTL 2 soat — qo'ng'iroq uzunligi + qayta ulanish uchun yetarli, lekin
    o'g'irlangan token'ning replay oynasini cheklaydi (avval 6 soat edi).
    """
    token = (
        AccessToken(
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
        .with_identity(participant_identity)
        .with_name(participant_name)
        .with_ttl(timedelta(hours=2))
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room_name,
                room_create=allow_create,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )

    return token.to_jwt()
