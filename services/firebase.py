"""Firebase Cloud Messaging (FCM) abstraction.

Lazy init — Firebase SDK faqat birinchi `send_push()` da ishga tushadi.
Credentials yo'q yoki noto'g'ri bo'lsa silently skip qiladi (dev'da OK).

Ishlatish:
    from services.firebase import send_push
    result = send_push(["token1", "token2"], "Title", "Body", {"key": "val"})
"""

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:
    firebase_admin = None
    credentials = None
    messaging = None

# `UnregisteredError`/`SenderIdMismatchError` mavjudligi firebase-admin
# versiyasiga bog'liq — lazy resolve va module-level cache.
if messaging is not None:
    _INVALID_TOKEN_EXC = tuple(
        exc for name in ("UnregisteredError", "SenderIdMismatchError")
        if (exc := getattr(messaging, name, None)) is not None
    )
else:
    _INVALID_TOKEN_EXC = ()

_app = None
_init_attempted = False


def _get_app():
    """Firebase app singleton — bir marta initsializatsiya qilinadi."""
    global _app, _init_attempted

    if _app is not None:
        return _app

    if _init_attempted:
        return None

    _init_attempted = True

    if firebase_admin is None:
        logger.warning("firebase-admin paketi o'rnatilmagan — push o'tkazib yuborildi")
        return None

    cred_path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", None)
    if not cred_path or not os.path.exists(cred_path):
        logger.warning(
            "Firebase credentials topilmadi (FIREBASE_CREDENTIALS_PATH=%s) — "
            "push o'tkazib yuborildi",
            cred_path,
        )
        return None

    try:
        cred = credentials.Certificate(cred_path)
        _app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initsializatsiya qilindi")
        return _app
    except Exception as e:
        logger.error("Firebase initsializatsiya xatosi: %s", e)
        return None


def _build_message(
    token: str,
    title: str,
    body: str,
    str_data: dict,
    data_only: bool,
    silent_background: bool = False,
):
    """FCM Message yaratadi. Uch rejim:

    - silent_background=True: APNS priority=5 + push-type=background (jim sync uchun).
      Apple iOS shu kombinatsiyani majburiy talab qiladi. `priority=10` bo'lsa rad.
      Android: data-only + priority=high (Doze rejimida ham uyg'otadi).
      `notification` bloki BO'LMAYDI.

    - data_only=True: APNS priority=10 + push-type=background + content-available.
      Maxsus case: incoming_call kabi (CallKit uyg'otadi). UI yo'q lekin tezda
      yetkaziladi.

    - Default (har ikkalasi False): ko'rinadigan push — notification bloki bilan.
    """
    if silent_background or data_only:
        # Ikkala rejim ham background push — bir xil payload, faqat apns-priority
        # farq qiladi:
        #   silent_background (priority=5) — ASL silent bracelet sync. Apple iOS
        #     shu kombinatsiyani majburiy talab qiladi (priority=10 bo'lsa rad).
        #   data_only (priority=10) — incoming_call kabi tezda yetkaziladigan case.
        # iOS content-available=1 + Android priority=high+data-only background
        # handler'ni uyg'otadi (killed app uchun ham).
        apns_priority = "5" if silent_background else "10"
        return messaging.Message(
            data=str_data,
            token=token,
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(
                headers={
                    "apns-priority": apns_priority,
                    "apns-push-type": "background",
                },
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(content_available=True),
                ),
            ),
        )
    return messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=str_data,
        token=token,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(sound="default"),
        ),
        # iOS: explicit aps alert + sound + push-type=alert. Avval faqat priority
        # header bor edi — APNs Auth Key Firebase'da to'g'ri bo'lsa ham ba'zi
        # iOS versiyalarda banner/sound kelmasligi mumkin edi.
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10", "apns-push-type": "alert"},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(title=title, body=body),
                    sound="default",
                ),
            ),
        ),
    )


def send_push(
    tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
    data_only: bool = False,
    silent_background: bool = False,
) -> dict:
    """FCM orqali bir nechta tokenga push yuboradi.

    Args:
        tokens: FCM tokenlar ro'yxati
        title: Push sarlavhasi (data_only/silent_background True bo'lsa e'tiborsiz)
        body: Push matni (data_only/silent_background True bo'lsa e'tiborsiz)
        data: Custom data payload — har doim yuboriladi (all string values)
        data_only: True bo'lsa — FAQAT data, notification bloki YO'Q.
            Maxsus case: incoming_call (APNS priority=10 + CallKit). VoIP push
            o'rnida emas — oddiy FCM token uchun. iOS app fonda bo'lsa uyg'onadi.
        silent_background: True bo'lsa — bracelet background sync uchun
            (APNS priority=5 + push-type=background + content-available=1).
            iOS Apple hujjati: app fonda bo'lsa uyg'onadi va sync qilishi mumkin.
            Force-quit yoki throttle holatda yetib bormaydi (best-effort).
            Bu silent push'ni NORMAL push'dan ajratish kerak — Apple priority=10
            background push'ni rad etadi.

    Returns:
        {
            "success_count": int,
            "failure_count": int,
            "invalid_tokens": [str],
        }
    """
    if not tokens:
        return {"success_count": 0, "failure_count": 0, "invalid_tokens": []}

    if _get_app() is None or messaging is None:
        return {
            "success_count": 0,
            "failure_count": len(tokens),
            "invalid_tokens": [],
        }

    str_data = {k: str(v) for k, v in (data or {}).items()}

    # firebase-admin 6.5.0 ning `send_each_for_multicast` worker thread'larida
    # OAuth2 credentials inject bo'lmaydi (bug) — har request `401 missing
    # credential` qaytaradi. Yechim: tokenlarni alohida `messaging.send()` orqali
    # ketma-ket yuborish. Mediik miqyosida (1-3 token / xabar) performance ta'siri
    # sezilarli emas. Multi-thread quyi-da yana yoqilishi mumkin firebase-admin
    # bug'i tuzatilgach.
    success_count = 0
    failure_count = 0
    invalid_tokens: list[str] = []

    for token in tokens:
        try:
            messaging.send(
                _build_message(token, title, body, str_data, data_only, silent_background)
            )
            success_count += 1
        except _INVALID_TOKEN_EXC:
            invalid_tokens.append(token)
            failure_count += 1
        except Exception as e:
            # `invalid-argument` ham token format xatosi bo'lishi mumkin
            code = getattr(e, "code", "")
            if code in ("invalid-argument", "registration-token-not-registered"):
                invalid_tokens.append(token)
            else:
                # Token (device identifikatori) log'ga yozilmaydi — faqat xato.
                logger.warning("FCM yuborish muvaffaqiyatsiz: error=%s", e)
            failure_count += 1

    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "invalid_tokens": invalid_tokens,
    }
