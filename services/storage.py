"""DigitalOcean Spaces + Bunny CDN integratsiya.

Upload: Presigned URL → mobile to'g'ridan-to'g'ri DO Spaces ga yuklaydi (ACL=private)
Download: Bunny CDN token URL → vaqt cheklangan, xavfsiz
Delete: boto3 orqali DO Spaces dan o'chirish
"""

import base64
import hashlib
import logging
import time
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

logger = logging.getLogger(__name__)


# Tibbiy fayllar uchun ruxsat etilgan MIME va max o'lcham. Mobile/web ushbu
# whitelist'dan tashqari yuborolmaydi (serializer ChoiceField'da enforce).
# Post-upload verification (head_object_or_none) shu chegaralarni S3'dagi
# real fayl bilan solishtirib tekshiradi — MIME spoofing va katta DoS file
# yuklash hujumini bloklash uchun.
ALLOWED_UPLOAD_MIMES = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/webp",
})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB — tibbiy rasm/PDF uchun yetarli

# MIME → fayl extension. Tibbiy fayl va audio uchun bir umumiy joy.
MIME_TO_EXT = {
    # Tibbiy fayllar (analiz natijasi va h.k.)
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/heic": "heic",
    "image/webp": "webp",
    # Audio (medical note dictation va h.k.)
    "audio/webm": "webm",
    "audio/mp3": "mp3",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
    "audio/aac": "aac",
}

# Audio MIME whitelist'ining yagona manbasi — MIME_TO_EXT audio bo'limidan
# olinadi. Gemini transcription (services/gemini.py) shu to'plamni import qiladi,
# shunda audio format ikki joyda nomuvofiq qolmaydi.
AUDIO_MIMES = frozenset(m for m in MIME_TO_EXT if m.startswith("audio/"))


def ext_for_mime(mime: str, fallback: str = "bin") -> str:
    """MIME tipidan fayl extension'ni qaytaradi."""
    return MIME_TO_EXT.get(mime, fallback)


_s3_client = None


def _get_s3_client():
    """boto3 S3 klient singleton — settings o'qilgandan keyin bir marta yaratiladi."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=settings.DO_SPACES_REGION,
            endpoint_url=settings.DO_SPACES_ENDPOINT,
            aws_access_key_id=settings.DO_SPACES_KEY,
            aws_secret_access_key=settings.DO_SPACES_SECRET,
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


def _ext_from_filename(file_name: str, fallback: str = "jpg") -> str:
    return file_name.rsplit(".", 1)[-1].lower() if "." in file_name else fallback


def _entity_keyed_path(prefix: str, entity_id: int, file_name: str) -> str:
    """Umumiy yo'l: {prefix}/{entity_id}/{uuid}.{ext}"""
    ext = _ext_from_filename(file_name)
    unique = uuid.uuid4().hex[:8]
    return f"{prefix}/{entity_id}/{unique}.{ext}"


def generate_avatar_key(user_id: int, file_name: str) -> str:
    """Avatar fayl yo'li: avatars/{user_id}/{uuid}.{ext}"""
    return _entity_keyed_path("avatars", user_id, file_name)


def generate_certificate_key(doctor_id: int, file_name: str) -> str:
    """Sertifikat fayl yo'li: certificates/{doctor_id}/{uuid}.{ext}"""
    return _entity_keyed_path("certificates", doctor_id, file_name)


def generate_file_key(room_id: int, file_name: str) -> str:
    """Chat fayl yo'li: chat/{room_id}/YYYY/MM/{uuid}_{filename}"""
    now = timezone.now()
    ext = _ext_from_filename(file_name, fallback="")
    unique = uuid.uuid4().hex[:8]
    safe_name = f"{unique}_{file_name}" if len(file_name) <= 50 else f"{unique}.{ext}"
    return f"chat/{room_id}/{now.year}/{now.month:02d}/{safe_name}"


def generate_upload_url(file_key: str, content_type: str, expires_in: int = 900) -> str:
    """DO Spaces presigned upload URL yaratadi (mobile PUT yuboradi).

    ACL qo'shilmaydi — Bunny CDN S3 auth orqali origin ga ulanadi. Xavfsizlik
    Bunny CDN token authentication orqali ta'minlanadi.
    """
    return _get_s3_client().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.DO_SPACES_BUCKET,
            "Key": file_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def generate_download_url(file_key: str, expiry_seconds: int = 3600) -> str:
    """Bunny CDN token URL yaratadi (MD5 + base64), vaqt cheklangan.

    Ref: https://docs.bunny.net/docs/cdn-token-authentication-basic
    """
    token_key = settings.BUNNY_TOKEN_KEY
    if not token_key:
        # Fail-CLOSED: production'da (DEBUG=False) imzosiz, access-control'siz
        # ochiq URL qaytarish butun maxfiy media'ni fosh qiladi. Faqat dev
        # rejimida (DEBUG=True) imzosiz fallback'ga ruxsat beramiz.
        if settings.DEBUG:
            return f"{settings.BUNNY_CDN_URL}/{file_key}"
        logger.critical(
            "BUNNY_TOKEN_KEY production'da sozlanmagan — imzosiz URL berilmaydi"
        )
        raise ImproperlyConfigured(
            "BUNNY_TOKEN_KEY production'da majburiy (imzosiz CDN URL xavfli)"
        )

    expiry_time = int(time.time()) + expiry_seconds
    file_path = f"/{file_key}"

    hash_raw = token_key + file_path + str(expiry_time)
    # MD5 — Bunny CDN signed-URL token sxemasi MAJBURIY talab qiladi (CDN tomoni
    # aynan MD5 token kutadi). Xavfsizlik-kritik hashing emas (CodeQL FP).
    token = (
        base64.b64encode(hashlib.md5(hash_raw.encode()).digest())  # noqa: S324
        .decode()
        .replace("\n", "")
        .replace("+", "-")
        .replace("/", "_")
        .replace("=", "")
    )

    return f"{settings.BUNNY_CDN_URL}{file_path}?token={token}&expires={expiry_time}"


def head_object_or_none(file_key: str) -> dict | None:
    """S3'dan fayl metadata (size + content type) — post-upload verify uchun.

    Fayl topilmasa yoki boshqa S3 xatosi — None (saqlash to'xtaydi).
    """
    try:
        obj = _get_s3_client().head_object(
            Bucket=settings.DO_SPACES_BUCKET, Key=file_key
        )
        return {
            "size": int(obj.get("ContentLength") or 0),
            "content_type": obj.get("ContentType", ""),
        }
    except ClientError as e:
        logger.warning("head_object failed for %s: %s", file_key, e)
        return None


def delete_file(file_key: str) -> bool:
    """DO Spaces dan faylni o'chiradi."""
    try:
        _get_s3_client().delete_object(
            Bucket=settings.DO_SPACES_BUCKET,
            Key=file_key,
        )
        logger.info("Fayl o'chirildi: %s", file_key)
        return True
    except Exception as e:
        logger.error("Fayl o'chirishda xato: %s — %s", file_key, e)
        return False


def download_file_bytes(file_key: str) -> tuple[bytes, str]:
    """DO Spaces dan faylni byte sifatida yuklab oladi.

    Returns:
        (file_bytes, content_type)

    Raises:
        Exception: agar fayl topilmasa yoki yuklab bo'lmasa
    """
    obj = _get_s3_client().get_object(Bucket=settings.DO_SPACES_BUCKET, Key=file_key)
    return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")


def upload_file_bytes(file_key: str, data: bytes, content_type: str) -> None:
    """DO Spaces ga server tomondan bayt yuklaydi (presigned PUT'siz).

    Odatda mobile/web presigned PUT bilan yuklaydi; bu helper server ichida
    qayta ishlangan fayl (masalan transcode qilingan m4a) ni yozish uchun.
    ACL qo'shilmaydi — Bunny CDN S3 auth orqali ulanadi (boshqa upload'lar bilan
    bir xil).

    Raises:
        Exception: S3 xatosi (chaqiruvchi retry qiladi)
    """
    _get_s3_client().put_object(
        Bucket=settings.DO_SPACES_BUCKET,
        Key=file_key,
        Body=data,
        ContentType=content_type,
    )
