"""Chat moduli uchun umumiy yordamchilar (helpers).

Xavfsizlik-kritik mantiq (fayl verify) bir joyda saqlanadi — WS consumer va
support reply view ikkalasi ham shu helper'ni chaqiradi (drift oldini olish).
"""

from django.conf import settings
from django.core.cache import cache

from services.storage import delete_file, head_object_or_none

# Online presence — bitta manba (key shabloni va TTL ilgari 5 joyda hardcoded edi).
# Flutter heartbeat har 60s'da keladi; 90s = 60s + 30s bufer. Heartbeat to'xtasa
# (iOS app muzlatilsa, telefon o'chsa) flag eng kechi 90s'da tushadi.
ONLINE_TTL = 90


def online_cache_key(user_id) -> str:
    return f"chat:online:{user_id}"


def is_online(user_id) -> bool:
    return bool(cache.get(online_cache_key(user_id)))


def set_online(user_id, online: bool, ttl: int = ONLINE_TTL) -> None:
    if online:
        cache.set(online_cache_key(user_id), True, timeout=ttl)
    else:
        cache.delete(online_cache_key(user_id))


# Last-seen — "oxirgi marta online" vaqti. Online flag 90s TTL bilan tushadi;
# last_seen esa uzoq saqlanadi (Redis, 30 kun) → "oxirgi marta 2 soat oldin"
# ko'rsatish uchun. Presence WS connect/heartbeat/offline'da yangilanadi. Faza 1'da
# faqat presence WS yozadi (chat-WS emas) — mobil presence'ga ulangach (Faza 2) to'liq.
LAST_SEEN_TTL = 60 * 60 * 24 * 30  # 30 kun


def last_seen_cache_key(user_id) -> str:
    return f"chat:last_seen:{user_id}"


def get_last_seen(user_id):
    return cache.get(last_seen_cache_key(user_id))


def set_last_seen(user_id, iso: str) -> None:
    cache.set(last_seen_cache_key(user_id), iso, timeout=LAST_SEEN_TTL)


def chat_peer_ids(user_id) -> list:
    """user bilan umumiy chat xonasi bor user id'lar (o'zidan tashqari).

    Presence broadcast nishoni — online-status REST'dagi BIR XIL xavfsizlik filtri
    (`chat_rooms__participants`). Faqat shu user bilan suhbatdosh user'lar uning
    presence'ini oladi (ID enumeration / begona presence leak oldini olish).
    """
    from app.users.models import User  # lazy — circular import oldini olish

    return list(
        User.objects.filter(chat_rooms__participants=user_id)
        .exclude(id=user_id)
        .values_list("id", flat=True)
        .distinct()
    )


def _message_type_for_mime(mime: str) -> str:
    """MIME prefix'idan chat message_type aniqlaydi."""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "file"


# Mobil ilovalar yuboradigan ovoz formatlari — bularni transcode QILMAYMIZ.
# iOS/Android allaqachon AAC/m4a/mp4 yuboradi; mp3/wav ham keng qo'llab-quvvatlanadi.
# Skip-logic AYNAN mobil jamoa bilan kelishilgan kontrakt — o'zgartirilmaydi.
_AUDIO_MIME_READY = frozenset({
    "audio/mp4",     # m4a (mobil)
    "audio/x-m4a",   # m4a alias
    "audio/aac",     # aac
    "audio/mpeg",    # mp3
    "audio/mp3",     # mp3 alias
    "audio/wav",     # wav
    "audio/x-wav",   # wav alias
})
# Web MediaRecorder ovozli xabar — webm/opus/ogg. Bularni m4a'ga transcode qilamiz.
_AUDIO_MIME_TRANSCODE = frozenset({
    "audio/webm",
    "audio/ogg",
    "audio/opus",
})

# Kengaytma bo'yicha fallback (S3 ContentType ishonchsiz bo'lsa).
_AUDIO_EXT_READY = frozenset({"m4a", "aac", "mp3", "mp4", "wav"})
_AUDIO_EXT_TRANSCODE = frozenset({"webm", "opus", "ogg"})


def _ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if name and "." in name else ""


def initial_audio_status(message_type: str, mime: str, file_name: str = "") -> str | None:
    """Yangi yaratilayotgan xabar uchun boshlang'ich `audio_status`.

    Kelishilgan skip-logic (mobil jamoa bilan):
      • audio EMAS                                  → None (audio_status yo'q)
      • mos format (m4a/aac/mp3/mp4/wav)            → "ready" (transcode YO'Q)
      • mos kelmaydigan (webm/opus/ogg)             → "pending" (transcode queue)

    MIME birinchi, kengaytma fallback. Noma'lum audio format ham "ready" deb
    qoldiriladi (transcode qilmaslik — buzuq fayl yaratishdan ko'ra xavfsizroq;
    client darhol original'ni ijro qiladi).
    """
    if message_type != "audio":
        return None

    mime = (mime or "").lower()
    if mime in _AUDIO_MIME_TRANSCODE:
        return "pending"
    if mime in _AUDIO_MIME_READY:
        return "ready"

    # MIME aniq bo'lmasa — kengaytmaga qaraymiz
    ext = _ext_of(file_name)
    if ext in _AUDIO_EXT_TRANSCODE:
        return "pending"
    # Qolgan barcha audio (mos ext yoki noma'lum) → transcode kerak emas
    return "ready"


def enqueue_transcode_if_pending(message_id: int, audio_status: str | None) -> None:
    """audio_status == "pending" bo'lsa transcode task'ni dedicated queue'ga qo'yadi.

    Redis/Celery o'chiq bo'lsa jim o'tadi (audio_status "pending"da qoladi — fallback
    sifatida client original webm'ni baribir ijro qila oladi, file_url o'zgarmaydi).

    DIQQAT: bu funksiya ASINXRON consumer'da TO'G'RIDAN-TO'G'RI chaqirilmasin —
    `.delay()` Celery broker bilan I/O qiladi. WS consumer'da uni
    `database_sync_to_async` sync-helper ICHIDA chaqiring (CLAUDE.md async qoidasi).
    """
    if audio_status != "pending":
        return
    try:
        # Lazy import — circular import (tasks → utils emas, lekin xavfsizlik uchun)
        from app.chat.tasks import transcode_voice_message

        transcode_voice_message.delay(message_id)
    except Exception:  # noqa: BLE001 — broker o'chiq bo'lsa skip
        pass


def verify_chat_upload(file_key: str) -> dict:
    """S3 HeadObject — yuklangan faylning HAQIQIY MIME/size'ini tekshiradi.

    Client "image/jpeg" deb URL olib, S3'ga ixtiyoriy bayt (masalan .exe) PUT
    qilishi mumkin — bu yerda real obyektni tekshiramiz va mos bo'lmasa faylni
    o'chiramiz (spoofing/malware + size DoS oldini olish).

    Eslatma: file_key'ning ayni shu xonaga tegishliligini (prefix tekshiruvi)
    chaqiruvchi tomon alohida bajaradi (room_id chaqiruvchida ma'lum).

    Returns: {"ok": bool, "error"?: str, "mime"?, "size"?, "message_type"?}
    """
    head = head_object_or_none(file_key)
    if head is None:
        return {"ok": False, "error": "Fayl yuklanmadi yoki topilmadi"}

    real_mime = head["content_type"] or ""
    real_size = head["size"]

    if real_mime not in settings.CHAT_ALLOWED_FILE_TYPES:
        delete_file(file_key)
        return {"ok": False, "error": f"Ruxsat etilmagan fayl turi: {real_mime}"}
    if real_size <= 0 or real_size > settings.CHAT_MAX_FILE_SIZE:
        delete_file(file_key)
        return {"ok": False, "error": "Fayl o'lchami chegaradan tashqari"}

    return {
        "ok": True,
        "mime": real_mime,
        "size": real_size,
        "message_type": _message_type_for_mime(real_mime),
    }
