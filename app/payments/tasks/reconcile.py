from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar
from .common import _PAYTECHUZ_STATES_CANCELLED,_PAYTECHUZ_STATE_PAID


@shared_task(base=BaseTask, bind=True, name="payments.reconcile_pending_payments")
def reconcile_pending_payments(self):
    """PENDING Payment'larni paytechuz Transaction bilan solishtirib reconcile qiladi.

    Stsenariy: bemor to'lagan, lekin webhook biz tomonga yetib kelmagan (network
    fail, server pad va h.k.). Provider esa paytechuz `Transaction` modelida
    yozuvni saqlagan. Biz har 30 daqiqada PENDING Payment'larga qaraymiz va
    paytechuz Transaction'da `state=2` (paid) ko'rsa, `_complete_payment`
    chaqiramiz (idempotent — agar allaqachon completed bo'lsa hech narsa qilmaydi).

    Cancelled stateni ham hisobga olamiz: provider'da bekor qilingan, lekin biz
    PENDING'da turibmiz → mahalliy Payment'ni CANCELLED qilamiz.

    24 soatdan eski PENDING'lar abandoned hisoblanadi va `expire_stale_payments`
    task tomondan tozalanadi (bu task faqat oxirgi 24h'ni qaraydi).
    """
    from paytechuz.integrations.django.models import PaymentTransaction

    from ..views import _complete_payment, _verify_webhook_amount

    cutoff = timezone.now() - timedelta(hours=24)
    pending = list(
        Payment.objects.filter(
            status=Payment.Status.PENDING,
            created_at__gte=cutoff,
        )
    )

    # N+1 oldini olish: barcha pending Payment uchun paytechuz tranzaksiyalarini
    # bitta so'rovda olamiz va (gateway, account_id) -> oxirgi txn xaritasini quramiz.
    # `order_by("-id")` => birinchi uchragan eng oxirgi tranzaksiya.
    txn_map: dict[tuple[str, str], object] = {}
    if pending:
        account_ids = [str(p.id) for p in pending]
        providers = list({p.provider for p in pending})
        for txn in PaymentTransaction.objects.filter(
            gateway__in=providers,
            account_id__in=account_ids,
        ).order_by("-id"):
            key = (txn.gateway, txn.account_id)
            txn_map.setdefault(key, txn)

    completed = 0
    cancelled = 0
    skipped = 0

    for payment in pending:
        txn = txn_map.get((payment.provider, str(payment.id)))
        if not txn:
            skipped += 1
            continue

        if txn.state == _PAYTECHUZ_STATE_PAID:
            if not _verify_webhook_amount(payment, txn):
                skipped += 1
                continue
            try:
                _complete_payment(payment.id)
                completed += 1
                logger.info(
                    "Reconciled Payment %s as COMPLETED (paytechuz Transaction %s)",
                    payment.id, txn.id,
                )
            except Exception:
                logger.exception(
                    "Reconcile failed for Payment %s (will retry next cycle)",
                    payment.id,
                )
        elif txn.state in _PAYTECHUZ_STATES_CANCELLED:
            payment.status = Payment.Status.CANCELLED
            if not payment.provider_transaction_id:
                payment.provider_transaction_id = txn.transaction_id or ""
            payment.save(
                update_fields=["status", "provider_transaction_id"]
            )
            cancelled += 1
            logger.info(
                "Reconciled Payment %s as CANCELLED (paytechuz state=%s)",
                payment.id, txn.state,
            )

    return {
        "completed": completed,
        "cancelled": cancelled,
        "skipped_no_txn": skipped,
        "scanned": len(pending),
    }


@shared_task(base=BaseTask, bind=True, name="payments.auto_mark_payouts_in_review")
def auto_mark_payouts_in_review(self):
    """Submitted PayoutRequest'larni N daqiqadan keyin avtomatik 'in_review' ga o'tkazadi.

    UI uchun: yangi yaratilgan payout `Yuborildi` (orange ↑), N daqiqadan keyin
    `Tekshirilmoqda` (blue clock). N — `SystemSetting.payout_in_review_after_minutes`
    (default 30). Admin'ning qo'l harakatisiz status oqimi ko'rinadi.

    Idempotent: status=pending AND sub_status=submitted shartiga mos kelganlarni
    bulk update qiladi.
    """
    threshold_min = SystemSetting.get_int(
        PAYOUT_IN_REVIEW_AFTER_KEY, PAYOUT_IN_REVIEW_AFTER_DEFAULT
    )

    cutoff = timezone.now() - timedelta(minutes=threshold_min)
    updated = PayoutRequest.objects.filter(
        status=PayoutRequest.Status.PENDING,
        sub_status=PayoutRequest.SubStatus.SUBMITTED,
        created_at__lte=cutoff,
    ).update(sub_status=PayoutRequest.SubStatus.IN_REVIEW)

    if updated:
        logger.info(
            "Auto-marked %d payouts as in_review (older than %d min)",
            updated, threshold_min,
        )
    return {"updated": updated, "threshold_minutes": threshold_min}


@shared_task(base=BaseTask, bind=True, name="payments.expire_stale_payments")
def expire_stale_payments(self):
    """24 soatdan eski PENDING Payment'larni CANCELLED qiladi (abandoned cart).

    Bemor "Sotib olish" bosib, Payme/Click sahifasiga o'tib, hech qanday harakat
    qilmasdan brauzerni yopsa — webhook umuman kelmaydi va Payment PENDING'da
    qoladi. 24 soatdan keyin uni CANCELLED deb belgilab, ma'lumot bazasini toza
    saqlaymiz va statistika to'g'ri chiqadi.

    Diqqat: agar webhook 24h dan keyin kech kelsa (juda kam holat), idempotent
    `_complete_payment` baribir to'g'ri ishlaydi va CANCELLED → COMPLETED ga
    o'tkazadi. Lekin `_complete_payment` bunda eski yozuvni ham qabul qiladi.
    """
    cutoff = timezone.now() - timedelta(hours=24)
    expired_qs = Payment.objects.filter(
        status=Payment.Status.PENDING,
        created_at__lt=cutoff,
    )
    count = expired_qs.update(status=Payment.Status.CANCELLED)
    if count:
        logger.info("Expired %d stale PENDING payments (>24h)", count)
    return {"expired": count}


