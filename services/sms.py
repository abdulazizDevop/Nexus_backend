"""Eskiz.uz SMS gateway klienti.

Auth flow: email + password → token (30 kun amal qiladi). Token Django
cache'ga (Redis) saqlanadi va eskirsa avtomatik refresh qilinadi.

Production'da OTP shabloni Eskiz tomonidan **oldindan tasdiqlanishi shart**
(test rejimida faqat 3 ta tayyor matn qabul qilinadi). Mediik shabloni:

    Mediik mobil ilovasiga kirish uchun tasdiqlash code: NNNN Kodni hech kimga bermang.

Doc: https://documenter.getpostman.com/view/663428/RzfmES4z
"""

import logging
from typing import Tuple

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("mediik.sms")

# Eskiz HTTP timeout — connect TEZ fail bo'lsin. Eskiz'ga ulanib bo'lmasa
# (tarmoq/firewall/whitelist) avval 15s blok bo'lib auth so'rovini gateway
# timeout'iga (502) olib borardi. connect=3s, read/write/pool=8s → eng yomon
# holatda ~3s da fail → auth so'rovi 502 bermay, "SMS yuborilmadi" qaytaradi.
_HTTP_TIMEOUT = httpx.Timeout(8.0, connect=3.0)

# Token Eskiz tomonida 30 kun amal qiladi — biz 25 kunga cache qilamiz, eskirish
# atrofida ehtimoliy 401'dan qutilish uchun bufferli.
_TOKEN_CACHE_KEY = "eskiz:token:v1"
_TOKEN_TTL_SEC = 60 * 60 * 24 * 25

# OTP shabloni — pozitsiya va matnni o'zgartirib bo'lmaydi (Eskiz moderatsiyasi
# tasdiqlangan formada). Faqat {code} (4 raqam) o'zgaradi.
OTP_SMS_TEMPLATE = (
    "Mediik mobil ilovasiga kirish uchun tasdiqlash code: {code}"
    " Kodni hech kimga bermang."
)


def _login() -> str:
    """Eskiz'ga email+password bilan login → token. Token cache'ga yoziladi."""
    email = settings.ESKIZ_EMAIL
    password = settings.ESKIZ_PASSWORD
    if not (email and password):
        logger.warning("Eskiz credentials missing — SMS yuborib bo'lmaydi")
        return ""

    try:
        resp = httpx.post(
            f"{settings.ESKIZ_BASE_URL}/api/auth/login",
            data={"email": email, "password": password},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        token = (resp.json() or {}).get("data", {}).get("token", "")
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Eskiz login failed: %s", exc)
        return ""

    if token:
        cache.set(_TOKEN_CACHE_KEY, token, _TOKEN_TTL_SEC)
    return token


def _get_token() -> str:
    """Cache'dan token yoki yangisini olish."""
    cached = cache.get(_TOKEN_CACHE_KEY)
    if cached:
        return cached
    return _login()


def _send_request(phone: str, message: str, token: str) -> Tuple[bool, dict]:
    """Bir marta Eskiz API'ga SMS yuborish. (ok, response_json) qaytaradi."""
    try:
        resp = httpx.post(
            f"{settings.ESKIZ_BASE_URL}/api/message/sms/send",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "mobile_phone": phone,
                "message": message,
                "from": settings.ESKIZ_FROM,
            },
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.error("Eskiz send error: phone=%s err=%s", phone, exc)
        return False, {}

    payload = {}
    try:
        payload = resp.json() if resp.content else {}
    except ValueError:
        pass

    if resp.status_code == 200 and (payload.get("status") or "").lower() in (
        "waiting",
        "success",
    ):
        return True, payload

    logger.warning(
        "Eskiz send failed: status=%s body=%s", resp.status_code, payload
    )
    return False, payload


def send_otp_via_sms(phone: str, code: str) -> bool:
    """OTP kodni SMS orqali yuborish.

    `phone` — normalize qilingan format ("998901234567"). Eskiz '+'siz qabul
    qiladi. Token eskirgan bo'lsa avtomatik refresh + qayta urinish.
    """
    if not phone or not code:
        return False

    token = _get_token()
    if not token:
        return False

    message = OTP_SMS_TEMPLATE.format(code=code)
    ok, payload = _send_request(phone, message, token)
    if ok:
        return True

    # 401/token_invalid — token eskirgan, qayta login + bir marta urinib ko'ramiz
    status = (payload.get("status") or "").lower()
    msg = (payload.get("message") or "").lower()
    if status == "token_invalid" or "token" in msg or "unauthor" in msg:
        cache.delete(_TOKEN_CACHE_KEY)
        token = _login()
        if not token:
            return False
        ok, _ = _send_request(phone, message, token)
        return ok

    return False
