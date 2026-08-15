"""High-level push notification helpers.

Boshqa app'lar shu funksiyalarni ishlatadi (firebase SDK ni o'zlari import qilmasin).

Ikki daraja:
  - `notify()` / `notify_users()` — DB yozuv (Notification) + push. Frontend
    "Bildirishnomalar" sahifasida ko'rinadigan xabarlar shu funksiyalar orqali
    yuboriladi. **Yangi kod shu yerda yozilsin.**
  - `send_to_user()` / `send_to_users()` — faqat push, DB yozuvsiz. Faqat
    ephemeral signallar uchun (incoming_call, silent data push, va h.k.).
"""

import logging

from django.db.models import Q

from services.firebase import send_push

from .catalog import render
from .models import DeviceToken, Notification

logger = logging.getLogger(__name__)


_EMPTY_RESULT = {"success_count": 0, "failure_count": 0, "invalid_tokens": []}


def _deactivate_invalid(invalid: list[str]) -> None:
    """Firebase qaytargan invalid tokenlarni is_active=False qiladi."""
    if not invalid:
        return
    DeviceToken.objects.filter(token__in=invalid).update(is_active=False)
    logger.info("Tozalandi: %d ta invalid FCM token", len(invalid))


def _push_to_user_ids(
    user_ids: list[int],
    title: str,
    body: str,
    data: dict | None,
    data_only: bool,
    app_scope: str | None,
    silent_background: bool = False,
    platform: str | None = None,
    strict_scope: bool = False,
) -> dict:
    """`send_to_user`/`send_to_users` umumiy core'i.

    `platform` ('ios'|'android') berilsa — faqat shu platforma tokenlariga
    yuboriladi.
    `strict_scope=True` — legacy null-scope tokenlarni qabul qilmaydi (cross-app
    leak'ni oldini olish uchun, masalan braslet faqat patient app'ga).
    """
    if not user_ids:
        return dict(_EMPTY_RESULT)
    qs = DeviceToken.objects.filter(
        user_id__in=user_ids,
        is_active=True,
        token_type=DeviceToken.TokenType.FCM,
    )
    if app_scope:
        if strict_scope:
            qs = qs.filter(app_scope=app_scope)
        else:
            qs = qs.filter(Q(app_scope=app_scope) | Q(app_scope__isnull=True))
    if platform:
        qs = qs.filter(platform=platform)
    tokens = list(qs.values_list("token", flat=True))
    if not tokens:
        return dict(_EMPTY_RESULT)

    result = send_push(
        tokens,
        title,
        body,
        data or {},
        data_only=data_only,
        silent_background=silent_background,
    )
    _deactivate_invalid(result.get("invalid_tokens", []))
    return result


# --- Low-level: faqat push (DB yozuvsiz) ---


def send_to_user(
    user,
    title: str,
    body: str,
    data: dict | None = None,
    data_only: bool = False,
    app_scope: str | None = None,
    silent_background: bool = False,
    platform: str | None = None,
    strict_scope: bool = False,
) -> dict:
    """Foydalanuvchining barcha aktiv FCM qurilmalariga push yuboradi.

    `data_only=True` — notification bloksiz (CallKit va silent push uchun).
    `silent_background=True` — bracelet background sync uchun (APNS priority=5).
    `platform` ('ios'|'android') — filter tokenlarni platforma bo'yicha.
    VoIP APNS tokenlari bu yerda ishlatilmaydi — alohida send_voip_to_user().

    `app_scope` — 'patient' | 'doctor' | 'admin' yoki None. Specific scope
    berilsa, faqat shu app tokenlariga yuboriladi (cross-app leak yo'q).
    Eski tokenlar (app_scope=null) backwards compat — har doim qabul qiladi.

    `strict_scope=True` — legacy null-scope tokenlarni qabul qilmaydi.
    Bracelet patient-only push'i uchun majburiy (doctor app'ga chiqib ketmasin).

    Ishlamagan tokenlarni avtomatik is_active=False qilib qo'yadi.
    """
    user_id = getattr(user, "id", None) if user else None
    if not user_id:
        return dict(_EMPTY_RESULT)
    return _push_to_user_ids(
        [user_id], title, body, data, data_only, app_scope,
        silent_background=silent_background, platform=platform,
        strict_scope=strict_scope,
    )


def send_to_users(
    users,
    title: str,
    body: str,
    data: dict | None = None,
    data_only: bool = False,
    app_scope: str | None = None,
    silent_background: bool = False,
    platform: str | None = None,
    strict_scope: bool = False,
) -> dict:
    """Bir nechta foydalanuvchilarga push (broadcast). Barcha tokenlar BITTA
    query bilan olinadi (N+1 yo'q — per-user `send_to_user` loop o'rniga)."""
    user_ids = [u.id for u in users if u and getattr(u, "id", None)]
    if not user_ids:
        return dict(_EMPTY_RESULT)
    return _push_to_user_ids(
        user_ids, title, body, data, data_only, app_scope,
        silent_background=silent_background, platform=platform, strict_scope=strict_scope,
    )


# --- High-level: DB yozuv + push ---


def _user_lang(user) -> str:
    """User'ning UserSettings'dagi tilini olish (default 'uz')."""
    return (
        getattr(getattr(user, "settings", None), "language", None) or "uz"
    )


def notify_by_key(
    user,
    type: str,
    key: str,
    params: dict | None = None,
    data: dict | None = None,
    send_push: bool = True,
    app_scope: str | None = None,
) -> Notification | None:
    """Catalog'dan til bo'yicha shablon olib yuborish.

    `key` — `app/notifications/catalog.py::NOTIFY_CATALOG` kalitlaridan biri.
    `params` — body matn'idagi {placeholder} larni .format(**params) bilan
    to'ldiradi. User'ning til'ini avtomatik aniqlaydi (UserSettings.language).
    """
    if not user or not getattr(user, "id", None):
        return None

    title, body = render(key, _user_lang(user), params=params)
    return notify(
        user=user,
        type=type,
        title=title,
        body=body,
        data=data,
        send_push=send_push,
        app_scope=app_scope,
    )


def notify(
    user,
    type: str,
    title: str,
    body: str,
    data: dict | None = None,
    send_push: bool = True,
    app_scope: str | None = None,
) -> Notification | None:
    """Notification yozuvini yaratadi va (xohlasa) push yuboradi.

    Frontend "Bildirishnomalar" sahifasida ko'rinishi kerak bo'lgan har qanday
    xabar shu funksiya orqali yuboriladi — bitta source of truth.

    Tarjima qo'llab-quvvatlash uchun `notify_by_key()` ishlating — u catalog'dan
    user.settings.language ga qarab tegishli matn'ni tanlaydi.

    Args:
        type: `Notification.Type` qiymatlaridan biri.
        send_push: False bo'lsa faqat DB ga yoziladi (silent in-app entry).
        app_scope: 'patient' | 'doctor' | 'admin' yoki None. Bitta user ikkala
            app'da (patient + doctor) login bo'lgan bo'lsa, push faqat shu
            scope tokenlariga boradi.
    """
    if not user or not getattr(user, "id", None):
        return None

    notification = Notification.objects.create(
        user=user,
        type=type,
        title=title,
        body=body,
        data=data or {},
        app_scope=app_scope,
    )

    if send_push:
        push_data = {
            **(data or {}),
            "type": type,
            "notification_id": str(notification.id),
        }
        try:
            send_to_user(user, title, body, push_data, app_scope=app_scope)
        except Exception:
            logger.exception(
                "Push yuborilmadi (notification #%s saqlandi)", notification.id
            )

    return notification


def notify_users(
    users,
    type: str,
    title: str,
    body: str,
    data: dict | None = None,
    send_push: bool = True,
    app_scope: str | None = None,
) -> int:
    """Bir nechta userlarga bir vaqtda Notification + push (broadcast).

    Returns: yaratilgan Notification yozuvlari soni.
    """
    user_list = [u for u in users if u and getattr(u, "id", None)]
    if not user_list:
        return 0

    Notification.objects.bulk_create(
        [
            Notification(
                user=u,
                type=type,
                title=title,
                body=body,
                data=data or {},
                app_scope=app_scope,
            )
            for u in user_list
        ]
    )

    if send_push:
        push_data = {**(data or {}), "type": type}
        try:
            send_to_users(user_list, title, body, push_data, app_scope=app_scope)
        except Exception:
            logger.exception("Broadcast push xatosi (DB yozuvlar saqlandi)")

    return len(user_list)
