"""Apple APNS VoIP push — iOS PushKit (CallKit incoming call ringtone).

Arxitektura:
    - Oddiy push (chat, eslatma) → FCM (services/firebase.py)
    - Incoming call (killed app ham uyg'onsin) → VoIP APNS → PushKit → CallKit

Sertifikat:
    - .p12 fayl PEM formatga aylantiriladi (openssl pkcs12 -in .. -out ..)
    - cert + key alohida yoki bitta PEM faylda
    - APNS_VOIP_CERT_PATH + APNS_VOIP_KEY_PATH settings

HTTP/2 talab qilinadi:
    - httpx[http2] paketi
    - Endpoint: api.push.apple.com (prod) yoki api.sandbox.push.apple.com (dev)

Headers:
    apns-topic: com.mediik.patient.voip  (bundle_id + .voip suffix)
    apns-push-type: voip                 (MAJBURIY iOS 13+)
    apns-priority: 10
    apns-expiration: <unix_ts>           (30 soniya — kelmasa qoldiradi)
"""

import json
import logging
import os
import time

import httpx
from django.conf import settings
from django.db.models import Q

logger = logging.getLogger(__name__)

_APNS_PROD = "https://api.push.apple.com"
_APNS_SANDBOX = "https://api.sandbox.push.apple.com"

_client: httpx.Client | None = None


def _get_client() -> httpx.Client | None:
    """httpx HTTP/2 klient — bir marta yaratiladi, certificate bilan."""
    global _client
    if _client is not None:
        return _client

    cert_path = getattr(settings, "APNS_VOIP_CERT_PATH", None)
    key_path = getattr(settings, "APNS_VOIP_KEY_PATH", None)

    if not cert_path or not key_path:
        logger.warning(
            "APNS VoIP cert path sozlanmagan (APNS_VOIP_CERT_PATH/KEY_PATH)"
        )
        return None

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        logger.warning(
            "APNS VoIP cert fayl topilmadi: cert=%s key=%s", cert_path, key_path
        )
        return None

    try:
        _client = httpx.Client(
            http2=True,
            cert=(cert_path, key_path),
            timeout=10.0,
        )
        logger.info("APNS VoIP HTTP/2 klient yaratildi")
        return _client
    except Exception as e:
        logger.error("APNS VoIP klient yaratishda xatolik: %s", e)
        return None


def _get_endpoint(environment: str | None = None) -> str:
    """APNS endpoint tanlash.

    Priority:
      1. Per-token environment ("development" → sandbox, "production" → prod)
      2. APNS_VOIP_USE_SANDBOX settings bayrog'i (fallback)

    TestFlight va App Store build — "production".
    Xcode debug build — "development".
    """
    if environment == "development":
        return _APNS_SANDBOX
    if environment == "production":
        return _APNS_PROD
    # Fallback: settings env var
    use_sandbox = getattr(settings, "APNS_VOIP_USE_SANDBOX", False)
    return _APNS_SANDBOX if use_sandbox else _APNS_PROD


def send_voip_push(
    device_token: str,
    payload: dict,
    expiration_seconds: int = 30,
    environment: str | None = None,
) -> dict:
    """Bitta iOS VoIP tokeniga PushKit push yuboradi.

    Args:
        device_token: Mobile'dan registratsiya qilingan VoIP token (hex string)
        payload: Call ma'lumoti — CallKit ishlatadi.
            Tavsiya qilinadigan format:
            {
                "aps": {"alert": "Incoming call"},  # majburiy emas lekin foydali
                "call_id": 123,
                "caller_id": 5,
                "caller_name": "Dr. Aziz Karimov",
                "caller_avatar_url": "https://...",
                "room_name": "meeting-abc",
                "meeting_type": "online",
                "livekit_token": "<optional JWT>"
            }
        expiration_seconds: Push muddati (default 30s — qo'ng'iroq tez bo'lishi kerak)

    Returns:
        {"success": bool, "status_code": int, "reason": str | None, "invalid_token": bool}
    """
    if not device_token:
        return {
            "success": False,
            "status_code": 0,
            "reason": "empty_token",
            "invalid_token": False,
        }

    client = _get_client()
    if client is None:
        return {
            "success": False,
            "status_code": 0,
            "reason": "apns_not_configured",
            "invalid_token": False,
        }

    topic = getattr(settings, "APNS_VOIP_TOPIC", "com.mediik.patient.voip")
    url = f"{_get_endpoint(environment)}/3/device/{device_token}"

    headers = {
        "apns-topic": topic,
        "apns-push-type": "voip",
        "apns-priority": "10",
        "apns-expiration": str(int(time.time()) + expiration_seconds),
    }

    try:
        response = client.post(url, content=json.dumps(payload), headers=headers)
    except httpx.HTTPError as e:
        logger.error("APNS VoIP HTTP xatosi: %s", e)
        return {
            "success": False,
            "status_code": 0,
            "reason": str(e),
            "invalid_token": False,
        }

    if response.status_code == 200:
        logger.info(
            "APNS VoIP muvaffaqiyatli: status=200 env=%s token=%s...",
            environment or "default",
            device_token[:20],
        )
        return {
            "success": True,
            "status_code": 200,
            "reason": None,
            "invalid_token": False,
        }

    # APNS error body: {"reason": "BadDeviceToken" | "Unregistered" | ...}
    try:
        reason = response.json().get("reason", "unknown")
    except ValueError:
        reason = response.text or "unknown"

    # Invalid token — tozalanishi kerak
    invalid_token = response.status_code in (400, 410) and reason in (
        "BadDeviceToken",
        "Unregistered",
        "DeviceTokenNotForTopic",
    )

    logger.warning(
        "APNS VoIP muvaffaqiyatsiz: status=%s reason=%s token=%s...",
        response.status_code,
        reason,
        device_token[:20],
    )

    return {
        "success": False,
        "status_code": response.status_code,
        "reason": reason,
        "invalid_token": invalid_token,
    }


def send_voip_to_user(user, payload: dict, app_scope: str | None = None) -> dict:
    """Foydalanuvchining barcha iOS VoIP tokenlariga push yuboradi.

    Har token uchun o'z `environment`'iga mos endpoint ishlatiladi
    (dev build → sandbox, TestFlight/prod → production).

    `app_scope` — bitta iPhone'da Patient va Doctor app o'rnatilgan bo'lsa,
    har app PushKit'da alohida VoIP token oladi. Specific app'ga (CallKit
    chaqiruv ekrani) yuborish uchun scope berish shart.

    Invalid tokenlarni avtomatik `is_active=False` qilib qo'yadi.
    """
    from app.notifications.models import DeviceToken

    if not user or not getattr(user, "id", None):
        return {"success_count": 0, "failure_count": 0, "invalid_tokens": []}

    qs = DeviceToken.objects.filter(
        user=user,
        token_type=DeviceToken.TokenType.VOIP_APNS,
        is_active=True,
    )
    if app_scope:
        qs = qs.filter(Q(app_scope=app_scope) | Q(app_scope__isnull=True))

    device_tokens = list(qs.values("token", "environment"))

    if not device_tokens:
        return {"success_count": 0, "failure_count": 0, "invalid_tokens": []}

    success_count = 0
    failure_count = 0
    invalid_tokens = []

    for dt in device_tokens:
        token = dt["token"]
        env = dt.get("environment") or "production"
        result = send_voip_push(token, payload, environment=env)
        if result["success"]:
            success_count += 1
        else:
            failure_count += 1
            if result.get("invalid_token"):
                invalid_tokens.append(token)

    if invalid_tokens:
        DeviceToken.objects.filter(token__in=invalid_tokens).update(is_active=False)
        logger.info("Tozalandi: %d ta invalid VoIP token", len(invalid_tokens))

    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "invalid_tokens": invalid_tokens,
    }
