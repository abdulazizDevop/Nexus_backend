"""Atmos karta gateway — direct HTTP API client.

Paytechuz'dan farqli: Atmos in-app card flow (foydalanuvchi Mediik app'dan
chiqmaydi — karta raqami + OTP shu yerda kiritiladi). Shu sababli
BasePaymentProvider'ga to'liq mos kelmaydi va alohida client class qilingan.

Flow:
1. _get_token()                       → Redis cache 50min
2. bind_card_init / bind_card_confirm → karta saqlash
3. pay_create + pay_pre_apply         → tranzaksiya + SMS
4. pay_apply                          → OTP bilan tasdiqlash → pul olinadi
5. verify_webhook                     → api_key tekshiruvi
"""

import base64
import hashlib
import hmac
import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("mediik.payments")

_TOKEN_CACHE_KEY = "atmos:token"
_HTTP_TIMEOUT = 15  # sek — Atmos kechikishi uchun
_TOKEN_BUFFER_SEC = 300  # token expires_in'dan necha sek oldin cache tugatamiz


class AtmosError(Exception):
    """Atmos API xatosi — code va description bilan."""

    def __init__(self, code: str, description: str, raw: dict | None = None):
        self.code = code
        self.description = description
        self.raw = raw or {}
        super().__init__(f"[{code}] {description}")


class AtmosClient:
    """Atmos APIga thin HTTP wrapper.

    Singleton kabi ishlatiladi — `from services.payments.atmos import atmos_client`.
    Konfiguratsiya `settings.ATMOS` dan o'qiladi.
    """

    def __init__(self):
        cfg = settings.ATMOS
        self.consumer_key = cfg["CONSUMER_KEY"]
        self.consumer_secret = cfg["CONSUMER_SECRET"]
        self.store_id = cfg["STORE_ID"]
        self.api_key = cfg["API_KEY"]
        self.base_url = cfg["BASE_URL"].rstrip("/")
        self.token_ttl = cfg["TOKEN_CACHE_TTL"]

    def is_configured(self) -> bool:
        return bool(self.consumer_key and self.consumer_secret and self.store_id)

    # ---------- Token ----------

    def _get_token(self) -> str:
        cached = cache.get(_TOKEN_CACHE_KEY)
        if cached:
            return cached

        creds = f"{self.consumer_key}:{self.consumer_secret}"
        basic = base64.b64encode(creds.encode()).decode()

        resp = requests.post(
            f"{self.base_url}/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error(
                "Atmos token olish xatosi: status=%s body=%s",
                resp.status_code, resp.text[:500],
            )
            raise AtmosError("token_error", f"Token olish xatosi (HTTP {resp.status_code})")

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise AtmosError("token_error", "access_token javobda yo'q")

        # Cache TTL'ni Atmos beradigan `expires_in`dan kelib chiqib hisoblaymiz —
        # buffer ayirib, hech qachon expired token cache'dan o'qilmasligi uchun.
        # Atmos docs'da `expires_in` 2525 yoki 3600 bo'lishi mumkin (ziddiyat) —
        # dinamik o'qish ikkalasiga ham mos keladi. Fallback `TOKEN_CACHE_TTL`.
        expires_in = data.get("expires_in")
        try:
            ttl = max(60, int(expires_in) - _TOKEN_BUFFER_SEC)
        except (TypeError, ValueError):
            ttl = self.token_ttl

        cache.set(_TOKEN_CACHE_KEY, token, ttl)
        logger.info(
            "Atmos yangi token olindi: expires_in=%s cache_ttl=%ss",
            expires_in, ttl,
        )
        return token

    # ---------- HTTP helper ----------

    def _request(self, method: str, path: str, json_body: dict, _retry: bool = True) -> dict:
        url = f"{self.base_url}{path}"
        token = self._get_token()
        resp = requests.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=json_body,
            timeout=_HTTP_TIMEOUT,
        )

        # Token muddati tugagan bo'lsa, 401 keladi — cache'ni tozalab qayta urinamiz
        if resp.status_code == 401 and _retry:
            cache.delete(_TOKEN_CACHE_KEY)
            logger.warning("Atmos 401 — token cache tozalandi, qayta urinish")
            return self._request(method, path, json_body, _retry=False)

        try:
            data = resp.json()
        except ValueError:
            logger.error("Atmos noJSON javob: status=%s body=%s", resp.status_code, resp.text[:500])
            raise AtmosError("invalid_response", f"JSON emas javob (HTTP {resp.status_code})")

        result = data.get("result", {}) if isinstance(data, dict) else {}
        code = result.get("code")
        if code and code != "OK":
            description = result.get("description", "Atmos xatosi")
            logger.warning("Atmos API xatosi: path=%s code=%s desc=%s", path, code, description)
            raise AtmosError(str(code), description, raw=data)

        return data

    # ---------- Card binding ----------

    def bind_card_init(self, card_number: str, expiry: str) -> dict:
        """SMS yuboradi karta egasiga. Atmos transaction_id qaytaradi.

        expiry: YYMM (masalan "2505")
        """
        return self._request(
            "POST",
            "/partner/bind-card/init",
            {"card_number": card_number, "expiry": expiry},
        )

    def bind_card_confirm(self, transaction_id: int, otp: str) -> dict:
        """OTP'ni tasdiqlaydi. Javobda card_id, card_token, pan, expiry keladi."""
        return self._request(
            "POST",
            "/partner/bind-card/confirm",
            {"transaction_id": transaction_id, "otp": otp},
        )

    def remove_card(self, card_id: int, card_token: str) -> dict:
        return self._request(
            "POST",
            "/partner/remove-card",
            {"id": card_id, "token": card_token},
        )

    # ---------- Payment ----------

    def pay_create(self, amount: int, account: str, lang: str = "uz") -> dict:
        """Atmos tomondagi tranzaksiya yaratadi. amount — tiyin'da.

        account: bizning order_id (Payment.id stringi) — webhook'da qaytadi.
        """
        body = {
            "amount": amount,
            "account": account,
            "store_id": self.store_id,
            "lang": lang,
        }
        return self._request("POST", "/merchant/pay/create", body)

    def pay_pre_apply(
        self, transaction_id: int, card_number: str, expiry: str
    ) -> dict:
        """Kartani tranzaksiyaga bog'laydi — Atmos karta egasiga SMS yuboradi.

        card_number — to'liq PAN (16 raqam). expiry — YYMM.
        """
        return self._request(
            "POST",
            "/merchant/pay/pre-apply",
            {
                "card_number": card_number,
                "expiry": expiry,
                "store_id": self.store_id,
                "transaction_id": transaction_id,
            },
        )

    def pay_apply(self, transaction_id: int, otp: str) -> dict:
        """OTP bilan to'lovni tasdiqlaydi — bu yerda pul olinadi.

        Javobda store_transaction (status_code, confirmed) va ofd_url keladi.
        """
        return self._request(
            "POST",
            "/merchant/pay/apply",
            {
                "transaction_id": transaction_id,
                "otp": otp,
                "store_id": self.store_id,
            },
        )

    # ---------- Webhook ----------

    def verify_webhook(self, body: dict[str, Any]) -> bool:
        """Atmos callback autentifikatsiyasi — `sign` MD5 hash tekshiruvi.

        Atmos body'da:
          sign = MD5(store_id + transaction_id + account + amount + api_key)
        `account` — pay/create da bizdan ketgan order_id (Payment.id stringi).
        Hujjatda `invoice` deyilgan, lekin amalda `account` field keladi.
        """
        if not self.api_key:
            return False

        received_sign = str(body.get("sign", "")).strip()
        if not received_sign:
            return False

        raw = (
            f"{body.get('store_id', '')}"
            f"{body.get('transaction_id', '')}"
            f"{body.get('account', '')}"
            f"{body.get('amount', '')}"
            f"{self.api_key}"
        )
        # MD5 — ATMOS imzo protokoli MAJBURIY talab qiladi (algoritmni o'zgartirib
        # bo'lmaydi, aks holda webhook verifikatsiyasi buziladi). Xavfsizlik-kritik
        # hashing emas — faqat ATMOS spec'iga mos imzoni solishtirish (CodeQL FP).
        expected_sign = hashlib.md5(raw.encode("utf-8")).hexdigest()  # noqa: S324
        return hmac.compare_digest(received_sign.lower(), expected_sign.lower())


# Singleton instance — settings.ATMOS bo'sh bo'lsa ham yaratiladi,
# is_configured() True qaytarganda ishlatiladi.
atmos_client = AtmosClient()
