"""ATMOS ASL API — payout client (doctor balansidan kartaga avtomatik o'tkazma).

Atmos ikki xil mahsulot beradi:
- Acquiring (services/payments/atmos.py) — patient karta orqali Mediik'ga to'laydi
- ASL (shu fayl)                          — Mediik depozitidan doctor kartasiga

ASL flow (4 bosqich):
1. _get_token()              → Redis cache (50min)
2. create_transaction()      → POST /create — draft (pul ko'chmaydi)
3. apply_transaction()       → POST /apply  — REAL pul ko'chadi (depozitdan yechiladi)
4. get_transaction()         → POST /id     — polling (webhook YO'Q!)

Status raqami:
- 1 raqam (4, 5)  → terminal (FINISHED / FAILED)
- 2 raqam (13)    → vaqtinchalik (PENDING — poll davom)
- 3 raqam (1xx, 2xx, 5xx) → error code

Pul birligi: TIYIN (1 so'm = 100 tiyin). Adashmang!

Hujjat: ASL API v1.0.1 (Innovative Payment Technologies, 2024).
"""

import base64
import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger("mediik.payments")

_TOKEN_CACHE_KEY = "atmos_asl:token"
_HTTP_TIMEOUT = 30  # sek — ASL /apply kechikishi mumkin (processing center javobini kutadi)
_TOKEN_BUFFER_SEC = 300

# Terminal state'lar — undan keyin polling to'xtatiladi
STATE_ACCEPTED = 2  # draft yaratildi (/create dan keyin)
STATE_FINISHED = 4  # ✅ muvaffaqiyatli (terminal)
STATE_FAILED = 5  # ❌ muvaffaqiyatsiz (terminal)
STATE_PENDING = 13  # ⏳ ishlanmoqda (polling kerak)

TERMINAL_STATES = (STATE_FINISHED, STATE_FAILED)


class AtmosAslError(Exception):
    """ASL API xatosi — code (int) va description bilan.

    ASL javob qaytarish formati: {"code": 0, "message": "OK", "description": "..."}
    code != 0 bo'lsa xato. Code uzunligi:
    - 3 raqam (100, 200, 500...) — server-side error
    - "transaction_failed" — bizning custom (state=5 bo'lganda)
    """

    def __init__(self, code: int | str, description: str, raw: dict | None = None):
        self.code = code
        self.description = description
        self.raw = raw or {}
        super().__init__(f"[{code}] {description}")


class AtmosAslClient:
    """ASL APIga thin HTTP wrapper. Singleton: `from services.payments.atmos_asl import atmos_asl_client`."""

    def __init__(self):
        cfg = settings.ATMOS_ASL
        self.username = cfg["USERNAME"]
        self.password = cfg["PASSWORD"]
        self.base_url = cfg["BASE_URL"].rstrip("/")
        self.token_ttl = cfg["TOKEN_CACHE_TTL"]

    def is_configured(self) -> bool:
        return bool(self.username and self.password and self.base_url)

    # ---------- Token ----------

    def _get_token(self) -> str:
        cached = cache.get(_TOKEN_CACHE_KEY)
        if cached:
            return cached

        creds = f"{self.username}:{self.password}"
        basic = base64.b64encode(creds.encode()).decode()

        # ATMOS /token endpoint — base URL'dan farqli (apigw.atmos.uz root)!
        # ASL docs (4-bet): POST https://apigw.atmos.uz/token?grant_type=client_credentials
        # grant_type — query string'da (hujjat talabi), body'da emas.
        token_url = f"{self._token_url()}?grant_type=client_credentials"

        resp = requests.post(
            token_url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.error(
                "ASL token olish xatosi: status=%s body=%s",
                resp.status_code, resp.text[:500],
            )
            raise AtmosAslError(
                "token_error", f"Token olish xatosi (HTTP {resp.status_code})"
            )

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise AtmosAslError("token_error", "access_token javobda yo'q")

        expires_in = data.get("expires_in")
        try:
            ttl = max(60, int(expires_in) - _TOKEN_BUFFER_SEC)
        except (TypeError, ValueError):
            ttl = self.token_ttl

        cache.set(_TOKEN_CACHE_KEY, token, ttl)
        logger.info(
            "ASL yangi token: expires_in=%s cache_ttl=%ss", expires_in, ttl
        )
        return token

    def _token_url(self) -> str:
        """Token endpoint URL'i — base_url'dan path qismini olib tashlaydi.

        base_url: "https://apigw.atmos.uz/out/1.0.0/asl"
        token:    "https://apigw.atmos.uz/token"
        """
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}/token"

    # ---------- HTTP helper ----------

    def _request(
        self, method: str, path: str, json_body: dict | None = None, _retry: bool = True
    ) -> dict:
        """ASL APIga so'rov yuboradi. Token'ni avto-refresh qiladi 401 paytida.

        Returns:
            dict — {"data": {...}, "code": 0, "message": "OK", "description": "..."}
        Raises:
            AtmosAslError — code != 0 yoki HTTP fail.
        """
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

        # 401 — token muddati o'tdi (yoki ATMOS rotate qilgan), cache tozalab qayta urin
        if resp.status_code == 401 and _retry:
            cache.delete(_TOKEN_CACHE_KEY)
            logger.warning("ASL 401 — token cache tozalandi, qayta urinish: %s", path)
            return self._request(method, path, json_body, _retry=False)

        try:
            data = resp.json()
        except ValueError:
            # 401 plain-text body (Spring/Tomcat default) — token refresh
            # ham yordam bermadi → credentials muammosi yoki partner_id
            # whitelist'da yo'q. Aniqroq error xabari bersak server'da
            # tezroq diagnostika qilinadi.
            if resp.status_code == 401:
                logger.error(
                    "ASL 401 (credentials/whitelist xato): path=%s body=%s",
                    path, resp.text[:300],
                )
                raise AtmosAslError(
                    "unauthorized",
                    "ATMOS ASL credentials xato yoki partner_id ASL endpoint'iga "
                    "whitelist qilinmagan. Server env'ni tekshiring: "
                    "ATMOS_ASL_USERNAME, ATMOS_ASL_PASSWORD.",
                )
            logger.error(
                "ASL noJSON javob: path=%s status=%s body=%s",
                path, resp.status_code, resp.text[:500],
            )
            raise AtmosAslError(
                "invalid_response", f"JSON emas javob (HTTP {resp.status_code})"
            )

        # ASL response format: {"data": {...}, "code": 0, "message": "OK", ...}
        # code != 0 → xato. code 100/101/102/103 — "noaniq" (uchun /id chaqirish kerak)
        code = data.get("code")
        if code != 0:
            description = data.get("description") or data.get("message") or "ASL xatosi"
            logger.warning(
                "ASL API xatosi: path=%s code=%s desc=%s", path, code, description
            )
            raise AtmosAslError(int(code) if isinstance(code, int) else code, description, raw=data)

        return data

    # ---------- Card info ----------

    def card_info(self, card_number: str) -> dict:
        """POST /info — karta raqami bo'yicha karta ma'lumotini olish.

        ASL avval kartani o'z DB'siga registrasiya qiladi, keyin `id` qaytaradi.
        Bizning ish: shu `id` ni DoctorPayoutCard.atmos_asl_card_id ga saqlash —
        keyingi /create chaqiriqlarida shu id bilan ishlaymiz.

        Args:
            card_number: 16 raqamli PAN (masked emas).

        Returns:
            {"data": {"id": 3, "name": "...", "pan": "8600...****9390",
                      "expiry": "2801", "phone": "998...", "bank_mfo": "00440",
                      "processing_type": "UZCARD"}, "code": 0, ...}
            DIQQAT: `expiry` — YYMM formatda ("2801" = 01/28, yil oldin, oy keyin).
            AtmosSavedCard.expiry help_text bilan mos. MMYY EMAS.
        """
        return self._request("POST", "/info", {"card_number": card_number})

    def card_by_id(self, card_id: int) -> dict:
        """POST /card/id — saqlangan karta ma'lumotini ASL id orqali olish."""
        return self._request("POST", "/card/id", {"card_id": card_id})

    # ---------- Transaction ----------

    def create_transaction(
        self, card_id: int, amount_tiyin: int, ext_id: str
    ) -> dict:
        """POST /create — draft yaratish (pul HALI ko'chmaydi).

        Args:
            card_id: ATMOS ASL'dagi karta id (oldindan /info orqali olingan).
            amount_tiyin: TIYIN'da! 50000 so'm = 5000000 tiyin.
            ext_id: noyob string (uuid4) — idempotency key.

        Returns:
            {"data": {"transaction_id": 2000557, "state": 2,
                      "amount": 5000000, "ext_id": "...", ...}, "code": 0}
        """
        return self._request(
            "POST",
            "/create",
            {"card_id": card_id, "amount": amount_tiyin, "ext_id": ext_id},
        )

    def apply_transaction(self, transaction_id: int) -> dict:
        """POST /apply — draft'ni tasdiqlash (REAL pul ko'chadi, depozit kamayadi).

        Javob state'i:
        - 4 (FINISHED) → muvaffaqiyatli, polling shart emas
        - 13 (PENDING) → kuting, /id orqali poll qiling
        - 5 (FAILED)   → muvaffaqiyatsiz, billing_error_message qarang
        """
        return self._request(
            "POST", "/apply", {"transaction_id": transaction_id}
        )

    def get_transaction(
        self, transaction_id: int | None = None, ext_id: str | None = None
    ) -> dict:
        """POST /id — tranzaksiya holatini olish (polling).

        Argumentlardan kamida bittasi shart. Ikkalasi bo'lsa transaction_id ustun.
        ext_id afzal — bizning UUID, har doim eslab turamiz, ATMOS tx_id yo'qolishi mumkin.
        """
        if not transaction_id and not ext_id:
            raise ValueError("Kamida transaction_id yoki ext_id berish kerak")

        body: dict[str, Any] = {}
        if transaction_id:
            body["transaction_id"] = transaction_id
        else:
            body["ext_id"] = ext_id
        return self._request("POST", "/id", body)

    # ---------- Deposit ----------

    def get_deposit(self) -> dict:
        """GET /deposit/current — joriy depozit qoldig'i (tiyinda).

        Returns:
            {"data": {"saldo": 48536026568, "partner_id": 71, ...}, "code": 0}
            saldo — joriy balans tiyinda (485 360 265.68 so'm).
        """
        return self._request("GET", "/deposit/current")

    def deposit_list(self, from_date: str, to_date: str, page: int = 1) -> dict:
        """POST /deposit-list — depozit pollanish tarixi (CREDIT/DEBIT operatsiyalar).

        Args:
            from_date / to_date: "YYYY-MM-DD" formatda.
            page: 1'dan boshlanadi (ASL 0-indexed qaytaradi javobida).
        """
        return self._request(
            "POST",
            "/deposit-list",
            {"from": from_date, "to": to_date, "page": page},
        )

    def transaction_list(
        self, from_date: str, to_date: str, page: int = 1
    ) -> dict:
        """POST /list — tranzaksiyalar ro'yxati (reconciliation uchun).

        Har sahifada 10 ta yozuv (per_page_size). Sahifa raqamlari 0-indexed.
        """
        return self._request(
            "POST",
            "/list",
            {"from": from_date, "to": to_date, "page": page},
        )


# Singleton — settings bo'sh bo'lsa ham yaratiladi, is_configured() tekshiriladi
atmos_asl_client = AtmosAslClient()
