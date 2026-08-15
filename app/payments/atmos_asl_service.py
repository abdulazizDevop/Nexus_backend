"""ASL payout orchestration — PayoutRequest'ni ATMOS ASL orqali bajaradi.

Bu modul ASL client'ni (services/payments/atmos_asl.py) Mediik modellariga
ulaydi. Client toza HTTP wrapper, bu yerda esa ish-logikasi:
- Karta /info orqali ASL'ga registrasiya (1 marta)
- /create + /apply chaqirish
- DoctorBalance'dan summani ushlash
- State terminal bo'lganda Payout completed/failed qilish
- PENDING bo'lsa Celery polling task'ni ishga tushirish

Flow:
    initiate_atmos_payout(payout_request)
      ├── register_card_if_needed()  ← /info → atmos_asl_card_id saqlash
      ├── /create                     ← draft + ext_id
      ├── /apply                      ← real transfer
      │   ├── state=4 → _mark_completed()
      │   ├── state=5 → _mark_failed()
      │   └── state=13 → schedule_poll() (Celery)
"""

import logging
import uuid
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from services.payments.atmos_asl import (
    STATE_FAILED,
    STATE_FINISHED,
    STATE_PENDING,
    AtmosAslError,
    atmos_asl_client,
)

from .utils import decimal_to_tiyin as _decimal_to_tiyin

if TYPE_CHECKING:
    from .models import DoctorPayoutCard, PayoutRequest

logger = logging.getLogger("mediik.payments")


def register_card_if_needed(card: "DoctorPayoutCard") -> int:
    """Kartani ASL'ga registrasiya qiladi (agar avval qilinmagan bo'lsa).

    ASL `/info` chaqiriladi → kartani ASL DB'siga qo'shadi va id qaytaradi.
    Shu id ni `DoctorPayoutCard.atmos_asl_card_id` ga saqlaymiz.

    Idempotent: agar `atmos_asl_card_id` allaqachon bor bo'lsa, hech narsa qilmaydi.

    Returns:
        atmos_asl_card_id (int)
    Raises:
        AtmosAslError — ASL xatosi (karta noto'g'ri, ASL DB'da yo'q, va h.k.)
    """
    if card.atmos_asl_card_id:
        return card.atmos_asl_card_id

    raw_pan = (card.card_number or "").replace(" ", "")
    if len(raw_pan) != 16:
        raise AtmosAslError(
            "invalid_card",
            f"Karta raqami 16 raqam bo'lishi shart (hozir: {len(raw_pan)})",
        )

    resp = atmos_asl_client.card_info(raw_pan)
    data = resp.get("data") or {}

    atmos_card_id = data.get("id")
    if not atmos_card_id:
        raise AtmosAslError(
            "invalid_response", "ASL /info javobida 'id' yo'q", raw=resp
        )

    card.atmos_asl_card_id = atmos_card_id
    card.atmos_asl_phone = data.get("phone", "") or ""
    card.atmos_asl_processing_type = data.get("processing_type", "") or ""
    card.save(
        update_fields=[
            "atmos_asl_card_id",
            "atmos_asl_phone",
            "atmos_asl_processing_type",
            "updated_at",
        ]
    )
    logger.info(
        "ASL karta registrasiya: card_id=%s atmos_asl_card_id=%s processing=%s",
        card.id, atmos_card_id, card.atmos_asl_processing_type,
    )
    return atmos_card_id


def initiate_atmos_payout(payout: "PayoutRequest") -> dict:
    """ASL payout'ni boshlaydi: /create → /apply, keyin state'ga qarab finalize.

    Args:
        payout: PayoutRequest (status=pending bo'lishi shart).

    Returns:
        {"state": int, "transaction_id": int, "ext_id": str, "completed": bool}

    Raises:
        AtmosAslError — ASL API xatosi
        ValueError    — payout noto'g'ri holatda (allaqachon completed va h.k.)
    """
    from .models import DoctorPayoutCard, PayoutRequest

    if payout.status != PayoutRequest.Status.PENDING:
        raise ValueError(
            f"PayoutRequest {payout.id} pending emas (status={payout.status})"
        )
    if payout.atmos_asl_transaction_id:
        # Avval boshlangan — get_transaction orqali holatni tekshirib qaytaramiz
        logger.info("ASL payout qayta urinish: payout=%s avval tx=%s",
                    payout.id, payout.atmos_asl_transaction_id)
        return _check_existing(payout)

    # Karta topish (snapshot'dan emas, real DoctorPayoutCard'dan — atmos_asl_card_id kerak)
    card = None
    if payout.card_id:
        card = DoctorPayoutCard.objects.filter(pk=payout.card_id).first()
    if not card:
        raise AtmosAslError(
            "card_not_found",
            "DoctorPayoutCard topilmadi (o'chirilgan bo'lishi mumkin)",
        )

    # 1. Karta ASL'da registratsiya qilingani tekshirish
    atmos_card_id = register_card_if_needed(card)

    # 2. ext_id yaratish (idempotency key) — har payout uchun bir marta
    ext_id = str(uuid.uuid4())
    amount_tiyin = _decimal_to_tiyin(payout.amount)

    # ext_id'ni /create dan OLDIN saqlash — agar /create transient xato (100-103)
    # qaytarsa va ATMOS'da tranzaksiya yaratilgan bo'lsa, biz keyin ext_id orqali
    # /id chaqirib holatini bila olamiz.
    payout.atmos_asl_ext_id = ext_id
    payout.method = PayoutRequest.Method.ATMOS_ASL
    payout.sub_status = PayoutRequest.SubStatus.ATMOS_PROCESSING
    payout.save(update_fields=["atmos_asl_ext_id", "method", "sub_status"])

    # 3. /create — draft
    try:
        create_resp = atmos_asl_client.create_transaction(
            card_id=atmos_card_id,
            amount_tiyin=amount_tiyin,
            ext_id=ext_id,
        )
    except AtmosAslError as exc:
        # PDF 19-bet: 100/101/102/103 — "требуется уточнять конечный статус транзакции".
        # Tranzaksiya ATMOS'da yaratilgan bo'lishi mumkin → ext_id orqali poll.
        if exc.code in (100, 101, 102, 103):
            logger.warning(
                "ASL /create transient xato (code=%s): payout=%s ext_id=%s — polling boshlanyapti",
                exc.code, payout.id, ext_id,
            )
            _schedule_poll(payout.id)
            return {
                "state": None,
                "transaction_id": None,
                "ext_id": ext_id,
                "completed": False,
                "polling": True,
                "error": exc.description,
            }
        _mark_failed(payout, exc.description, state=None)
        raise

    create_data = create_resp.get("data") or {}

    # Currency tekshiruvi — UZS bo'lishi shart (hujjat 8-bet: currency field)
    currency = create_data.get("currency")
    if currency and currency != "UZS":
        _mark_failed(
            payout,
            f"ASL /create kutilmagan valyuta: {currency} (UZS bo'lishi shart)",
            state=None,
        )
        raise AtmosAslError(
            "invalid_currency",
            f"Kutilmagan valyuta: {currency}",
            raw=create_resp,
        )

    atmos_tx_id = create_data.get("transaction_id")
    if not atmos_tx_id:
        _mark_failed(payout, "ASL /create javobida transaction_id yo'q", state=None)
        raise AtmosAslError("invalid_response", "transaction_id yo'q", raw=create_resp)

    # transaction_id va state'ni saqlaymiz (ext_id avval saqlangan)
    payout.atmos_asl_transaction_id = atmos_tx_id
    payout.atmos_asl_state = create_data.get("state")
    payout.save(
        update_fields=[
            "atmos_asl_transaction_id",
            "atmos_asl_state",
        ]
    )

    # 4. /apply — REAL transfer
    try:
        apply_resp = atmos_asl_client.apply_transaction(atmos_tx_id)
    except AtmosAslError as exc:
        # Apply xatosi — apply qilmagan/yarim qolgan bo'lishi mumkin.
        # /id orqali aniqlash uchun polling'ga yuboramiz (manual reject emas).
        logger.warning(
            "ASL /apply xato: payout=%s tx=%s err=%s — polling boshlanyapti",
            payout.id, atmos_tx_id, exc,
        )
        _schedule_poll(payout.id)
        return {
            "state": None,
            "transaction_id": atmos_tx_id,
            "ext_id": ext_id,
            "completed": False,
            "polling": True,
            "error": exc.description,
        }

    apply_data = apply_resp.get("data") or {}

    # Currency check ham /apply javobida
    apply_currency = apply_data.get("currency")
    if apply_currency and apply_currency != "UZS":
        logger.critical(
            "ASL /apply kutilmagan valyuta: payout=%s tx=%s currency=%s",
            payout.id, atmos_tx_id, apply_currency,
        )

    state = apply_data.get("state")
    return _handle_state(payout, state, apply_data)


def _check_existing(payout: "PayoutRequest") -> dict:
    """Avval boshlangan payout uchun /id chaqirib holatni yangilaydi."""
    try:
        resp = atmos_asl_client.get_transaction(
            transaction_id=payout.atmos_asl_transaction_id
        )
    except AtmosAslError as exc:
        logger.warning("ASL /id xato (existing check): payout=%s err=%s", payout.id, exc)
        return {
            "state": payout.atmos_asl_state,
            "transaction_id": payout.atmos_asl_transaction_id,
            "ext_id": payout.atmos_asl_ext_id,
            "completed": False,
            "error": exc.description,
        }

    data = resp.get("data") or {}
    return _handle_state(payout, data.get("state"), data)


def _handle_state(payout: "PayoutRequest", state: int | None, data: dict) -> dict:
    """State'ga qarab payout'ni finalize qiladi yoki polling boshlaydi."""
    if state == STATE_FINISHED:
        _mark_completed(payout, state=state, data=data)
        completed = True
        polling = False
    elif state == STATE_FAILED:
        error_msg = data.get("billing_error_message") or "ASL: muvaffaqiyatsiz"
        _mark_failed(payout, error_msg, state=state)
        completed = False
        polling = False
    elif state == STATE_PENDING:
        payout.atmos_asl_state = state
        payout.save(update_fields=["atmos_asl_state"])
        _schedule_poll(payout.id)
        completed = False
        polling = True
    else:
        # Notanish state — log va polling
        logger.warning(
            "ASL notanish state: payout=%s state=%s data=%s",
            payout.id, state, data,
        )
        payout.atmos_asl_state = state if state is not None else 0
        payout.save(update_fields=["atmos_asl_state"])
        _schedule_poll(payout.id)
        completed = False
        polling = True

    return {
        "state": state,
        "transaction_id": payout.atmos_asl_transaction_id,
        "ext_id": payout.atmos_asl_ext_id,
        "completed": completed,
        "polling": polling,
    }


def _notify_doctor_payout(payout: "PayoutRequest", notif_type, title: str, body: str) -> None:
    """Doctor'ga payout statusi haqida push yuboradi (notifications.utils orqali).

    _mark_completed va _mark_failed bir xil shaklda push yuboradi — faqat
    type/title/body farq qiladi. Import va try/except shu yerda jamlangan.
    """
    try:
        from app.notifications.utils import notify
        notify(
            payout.doctor.user,
            type=notif_type,
            title=title,
            body=body,
            data={"payout_id": str(payout.id)},
            app_scope="doctor",
        )
    except Exception:
        logger.exception("Doctor'ga payout push yuborishda xato (payout=%s)", payout.id)


def _mark_completed(payout: "PayoutRequest", state: int, data: dict) -> None:
    """Payout completed: status=completed, sub_status (UI 'paid'), DoctorBalance'dan yech.

    Atomic — DoctorBalance.confirm_withdrawal'ni shu transaction ichida chaqiramiz.
    """
    from .models import DoctorBalance, PayoutRequest

    with transaction.atomic():
        # Race condition: ikki marta complete qilinishidan saqlanish
        updated = PayoutRequest.objects.filter(
            pk=payout.pk,
            status=PayoutRequest.Status.PENDING,
        ).update(
            status=PayoutRequest.Status.COMPLETED,
            atmos_asl_state=state,
            atmos_asl_error="",
            transaction_ref=str(payout.atmos_asl_transaction_id or ""),
            processed_at=timezone.now(),
        )

        if not updated:
            # Avval kim tomonidan complete qilingan — DoctorBalance'dan ikki marta
            # yechilmasligi uchun chiqib ketamiz.
            logger.info(
                "ASL payout allaqachon terminal holatda: payout=%s — skip",
                payout.id,
            )
            return

        # DoctorBalance'dan summani yechish (atomic F() ichida)
        balance = DoctorBalance.objects.filter(doctor_id=payout.doctor_id).first()
        if balance:
            balance.confirm_withdrawal(payout.amount)

    payout.refresh_from_db()
    logger.info(
        "ASL payout COMPLETED: payout=%s amount=%s doctor=%s",
        payout.id, payout.amount, payout.doctor_id,
    )

    # Doctor'ga push (notifications.utils)
    from app.notifications.models import Notification
    _notify_doctor_payout(
        payout,
        Notification.Type.PAYOUT_COMPLETED,
        "Pul kartangizga tushdi",
        f"{payout.amount} so'm **** {payout.card_last4} kartaga muvaffaqiyatli o'tkazildi.",
    )


def _mark_failed(
    payout: "PayoutRequest", error_msg: str, state: int | None
) -> None:
    """Payout failed: status=rejected (DoctorBalance o'zgarmaydi)."""
    from .models import PayoutRequest

    updated = PayoutRequest.objects.filter(
        pk=payout.pk,
        status=PayoutRequest.Status.PENDING,
    ).update(
        status=PayoutRequest.Status.REJECTED,
        atmos_asl_state=state,
        atmos_asl_error=error_msg[:500],
        rejection_reason=f"ATMOS ASL: {error_msg}"[:500],
        processed_at=timezone.now(),
    )
    if updated:
        logger.warning(
            "ASL payout FAILED: payout=%s state=%s err=%s",
            payout.id, state, error_msg,
        )
        # Doctor'ga push
        from app.notifications.models import Notification
        _notify_doctor_payout(
            payout,
            Notification.Type.PAYOUT_REJECTED,
            "Pul yechish bajarilmadi",
            f"Sabab: {error_msg}. Pul balansingizda saqlanib qoldi.",
        )


def _schedule_poll(payout_id: int) -> None:
    """Celery task ishga tushiradi — 5s dan keyin /id chaqiradi."""
    from django.conf import settings as dj_settings

    from .tasks import poll_atmos_asl_payout

    countdown = dj_settings.ATMOS_ASL["POLL_COUNTDOWN_SEC"]
    poll_atmos_asl_payout.apply_async(args=[payout_id], countdown=countdown)
