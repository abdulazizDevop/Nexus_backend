from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


# ---------- ATMOS ASL polling ----------


@shared_task(
    base=BaseTask,
    bind=True,
    name="payments.poll_atmos_asl_payout",
    autoretry_for=(),  # qo'lda retry (countdown), BaseTask'ning auto retry'sini o'chiramiz
)
def poll_atmos_asl_payout(self, payout_id: int):
    """ASL payout PENDING (state=13) bo'lganda /id orqali holatini tekshiradi.

    PENDING bo'lsa o'zini-o'zi qayta jadvalga qo'yadi (max POLL_MAX_RETRIES marta).
    Terminal (4/5) bo'lsa _handle_state ichida payout finalize qilinadi.

    Webhook YO'Q — ATMOS ASL callback bermaydi. Faqat polling.
    """
    from services.payments.atmos_asl import (
        STATE_FAILED,
        STATE_FINISHED,
        STATE_PENDING,
        AtmosAslError,
        atmos_asl_client,
    )

    from ..atmos_asl_service import _handle_state

    payout = PayoutRequest.objects.filter(
        pk=payout_id,
        status=PayoutRequest.Status.PENDING,
    ).first()
    if not payout:
        logger.info("ASL poll: payout %s PENDING emas yoki yo'q — to'xtatildi", payout_id)
        return {"skipped": True, "reason": "not pending"}

    if not payout.atmos_asl_transaction_id and not payout.atmos_asl_ext_id:
        logger.warning(
            "ASL poll: payout %s da tx_id ham ext_id ham yo'q — to'xtatildi",
            payout_id,
        )
        return {"skipped": True, "reason": "no atmos ids"}

    # Poll count'ni oshirish (debug uchun)
    PayoutRequest.objects.filter(pk=payout_id).update(
        atmos_asl_poll_count=F("atmos_asl_poll_count") + 1
    )

    # /id chaqirish — ext_id afzal (har doim eslab turamiz)
    try:
        resp = atmos_asl_client.get_transaction(
            ext_id=payout.atmos_asl_ext_id or None,
            transaction_id=(
                payout.atmos_asl_transaction_id if not payout.atmos_asl_ext_id else None
            ),
        )
    except AtmosAslError as exc:
        logger.warning(
            "ASL poll xato: payout=%s err=%s retries=%s/%s",
            payout_id, exc, self.request.retries,
            settings.ATMOS_ASL["POLL_MAX_RETRIES"],
        )
        # Network-level xato — qayta urinamiz
        _retry_or_fail(self, payout, f"ASL /id xato: {exc.description}")
        return {"error": exc.description, "retried": True}

    data = resp.get("data") or {}
    state = data.get("state")

    if state in (STATE_FINISHED, STATE_FAILED):
        # Terminal — finalize
        payout.refresh_from_db()
        _handle_state(payout, state, data)
        return {"state": state, "terminal": True}

    if state == STATE_PENDING:
        # Hali ishlanmoqda — qayta urinamiz
        _retry_or_fail(self, payout, "PENDING (ASL hali javob bermaganligi)")
        return {"state": state, "retried": True}

    # Notanish state — log va qayta urinish
    logger.warning("ASL poll notanish state: payout=%s state=%s data=%s",
                   payout_id, state, data)
    _retry_or_fail(self, payout, f"Notanish state: {state}")
    return {"state": state, "retried": True}


def _retry_or_fail(task_self, payout: PayoutRequest, last_reason: str) -> None:
    """Polling retry'ini qayta jadvalga qo'yadi yoki retries tugagan bo'lsa fail qiladi."""
    max_retries = settings.ATMOS_ASL["POLL_MAX_RETRIES"]
    countdown = settings.ATMOS_ASL["POLL_COUNTDOWN_SEC"]

    if task_self.request.retries < max_retries:
        raise task_self.retry(countdown=countdown, max_retries=max_retries)

    # Retries tugadi — ASL hali ham terminal bermadi. Manual review uchun
    # belgilaymiz: rejected qilmaymiz, lekin admin'ga signal kerak.
    logger.critical(
        "ASL polling timeout: payout=%s tx=%s ext=%s retries=%s",
        payout.id, payout.atmos_asl_transaction_id,
        payout.atmos_asl_ext_id, task_self.request.retries,
    )
    payout.atmos_asl_error = f"Polling timeout: {last_reason}"
    payout.save(update_fields=["atmos_asl_error"])
    # NB: status'ni o'zgartirmaymiz — admin qo'lda /id chaqirib aniqlashi kerak.
    # Reconciliation task (atmos_asl_reconcile) ham keyin avtomatik tekshiradi.


# ---------- ATMOS ASL auto-retry (failed initial attempt) ----------


@shared_task(base=BaseTask, bind=True, name="payments.retry_pending_asl_payouts")
def retry_pending_asl_payouts(self):
    """ASL'ga yetib bormagan pending payout'larni qayta urinish.

    Auto-payout `POST /doctor/payouts/` ichida ASL darrov chaqiriladi. Lekin
    ASL down/timeout/401 bo'lsa, payout `pending` qoladi (transaction_id
    yo'q — ya'ni ASL'da hech qachon yaratilmagan). Bu task shu situatsiyani
    tuzatadi.

    Har 5 daqiqada (CELERY_BEAT_SCHEDULE) ishlaydi. Atmos vaqtinchalik
    o'chiq bo'lsa ham, qaytadan ishlay boshlasa darrov tushadi.

    24 soatdan eski pending payout'larga tegmaymiz (ehtimol prod-related
    chuqurroq muammo — admin ko'rib chiqishi kerak).
    """
    from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

    from ..atmos_asl_service import initiate_atmos_payout

    if not atmos_asl_client.is_configured():
        return {"skipped": True, "reason": "ATMOS ASL sozlanmagan"}

    cutoff = timezone.now() - timedelta(hours=24)
    stuck = PayoutRequest.objects.filter(
        status=PayoutRequest.Status.PENDING,
        atmos_asl_transaction_id__isnull=True,  # ASL'da hech qachon yaratilmagan
        created_at__gte=cutoff,
    )

    total = 0
    succeeded = 0
    failed = 0
    for payout in stuck:
        total += 1
        try:
            result = initiate_atmos_payout(payout)
            if result.get("completed") or result.get("polling"):
                succeeded += 1
        except AtmosAslError as exc:
            failed += 1
            logger.warning(
                "retry_pending_asl: payout=%s code=%s desc=%s",
                payout.id, exc.code, exc.description,
            )
        except Exception:
            failed += 1
            logger.exception(
                "retry_pending_asl: payout=%s kutilmagan xato", payout.id
            )

    if total:
        logger.info(
            "retry_pending_asl_payouts: %d tekshirildi, %d ishladi, %d xato",
            total, succeeded, failed,
        )
    return {"total": total, "succeeded": succeeded, "failed": failed}


# ---------- ATMOS ASL reconciliation ----------


@shared_task(base=BaseTask, bind=True, name="payments.atmos_asl_reconcile")
def atmos_asl_reconcile(self):
    """Kunlik ASL sverka — ATMOS'dagi tranzaksiyalar bilan bizning DB'ni solishtiradi.

    Maqsadi: polling crash bo'lgan, retries tugagan, yoki worker o'lgan paytdagi
    payout'larni topib avtomatik finalize qilish. Shuningdek, ATMOS'da bor, bizda
    yo'q tranzaksiyalarni log'da CRITICAL bilan belgilash (manual aralashish kerak).

    Hujjat 15-bet: POST /list — "получение информации об имеющихся в системе
    транзакциях".

    Algoritm:
    1. ATMOS /list ni so'ngi 2 kun uchun chaqiramiz (page=0..N).
    2. Har ATMOS tx uchun ext_id orqali bizning PayoutRequest topamiz.
       - Topilsa va status mos kelmasa: state=4 → completed, state=5 → rejected
       - Topilmasa: CRITICAL log (orphan tx — admin tekshirsin)
    3. Bizning PENDING payout'lar uchun ATMOS'da yo'qotilganlarini ham aniqlash mumkin
       (lekin bu rare — odatda polling topib qo'yadi).
    """
    from services.payments.atmos_asl import (
        STATE_FAILED,
        STATE_FINISHED,
        AtmosAslError,
        atmos_asl_client,
    )

    from ..atmos_asl_service import _mark_completed, _mark_failed

    if not atmos_asl_client.is_configured():
        logger.info("ASL reconcile: konfiguratsiya yo'q — skip")
        return {"skipped": True, "reason": "not configured"}

    today = timezone.localdate()
    from_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    reconciled_finished = 0
    reconciled_failed = 0
    orphan_count = 0
    skipped_already_terminal = 0

    page = 0
    max_pages = 50  # xavfsizlik chegarasi (500 tx/sahifa × 50 = 25k)

    while page < max_pages:
        try:
            resp = atmos_asl_client.transaction_list(
                from_date=from_date, to_date=to_date, page=page
            )
        except AtmosAslError as exc:
            logger.warning(
                "ASL reconcile /list xato: page=%s err=%s",
                page, exc,
            )
            break

        data = resp.get("data") or {}
        transactions = data.get("transactions") or []
        if not transactions:
            break

        for tx in transactions:
            ext_id = tx.get("ext_id")
            tx_id = tx.get("transaction_id")
            state = tx.get("state")

            if not ext_id:
                # ATMOS tx ext_id'siz — bizning bo'lishi mumkin emas (har doim uuid yuboramiz)
                continue

            payout = PayoutRequest.objects.filter(
                atmos_asl_ext_id=ext_id
            ).first()

            if not payout:
                # ATMOS'da bor, bizda yo'q — CRITICAL
                logger.critical(
                    "ASL reconcile ORPHAN: ATMOS tx=%s ext_id=%s state=%s — bizda PayoutRequest yo'q!",
                    tx_id, ext_id, state,
                )
                orphan_count += 1
                continue

            if payout.status != PayoutRequest.Status.PENDING:
                skipped_already_terminal += 1
                continue

            # PENDING — ATMOS state'iga qarab finalize qilamiz
            if state == STATE_FINISHED:
                _mark_completed(payout, state=state, data=tx)
                reconciled_finished += 1
                logger.info(
                    "ASL reconcile: payout=%s FINISHED qilindi (ATMOS tx=%s)",
                    payout.id, tx_id,
                )
            elif state == STATE_FAILED:
                error_msg = tx.get("billing_error_message") or "Reconcile: ASL state=5"
                _mark_failed(payout, error_msg, state=state)
                reconciled_failed += 1
                logger.info(
                    "ASL reconcile: payout=%s REJECTED qilindi (ATMOS tx=%s err=%s)",
                    payout.id, tx_id, error_msg,
                )
            # state 13/2 bo'lsa qoldiramiz — polling baribir davom etayotgan bo'ladi

        # Sahifalash — per_page_size yetishmasa tugatamiz
        per_page = data.get("per_page_size", 10)
        size = data.get("size", 0)
        total_pages = data.get("total_page_size") or ((size + per_page - 1) // per_page if per_page else 1)
        page += 1
        if page >= total_pages:
            break

    summary = {
        "from": from_date,
        "to": to_date,
        "reconciled_finished": reconciled_finished,
        "reconciled_failed": reconciled_failed,
        "orphan_atmos_tx": orphan_count,
        "skipped_already_terminal": skipped_already_terminal,
        "pages_scanned": page,
    }
    logger.info("ASL reconcile yakuni: %s", summary)
    return summary


# ---------- ATMOS ASL deposit low-balance alert ----------


@shared_task(base=BaseTask, bind=True, name="payments.atmos_asl_deposit_alert")
def atmos_asl_deposit_alert(self):
    """ATMOS ASL depozit balansini tekshiradi va past bo'lsa adminga signal yuboradi.

    Hujjat 12-bet: GET /deposit/current → saldo (tiyinda).
    Threshold: settings.ATMOS_ASL["MIN_DEPOSIT_WARN_SUM"] (so'mda).

    Past bo'lsa: super admin'larga FCM push + Telegram xabar.
    """
    from services.payments.atmos_asl import AtmosAslError, atmos_asl_client

    if not atmos_asl_client.is_configured():
        return {"skipped": True, "reason": "not configured"}

    try:
        resp = atmos_asl_client.get_deposit()
    except AtmosAslError as exc:
        logger.warning("ASL deposit alert /deposit/current xato: %s", exc)
        return {"error": exc.description}

    data = resp.get("data") or {}
    saldo_tiyin = data.get("saldo") or 0
    saldo_sum = saldo_tiyin / 100
    threshold = settings.ATMOS_ASL["MIN_DEPOSIT_WARN_SUM"]

    if saldo_sum >= threshold:
        return {"ok": True, "saldo_sum": saldo_sum, "threshold": threshold}

    # Spam himoyasi — kunda maksimum 2 marta xabar (12 soatlik cooldown).
    # Beat har 6 soatda ishlasa ham, xabar 12 soatda 1 marta yuboriladi.
    from django.core.cache import cache as _alert_cache

    cooldown_key = "atmos_asl:deposit_alert:cooldown"
    if _alert_cache.get(cooldown_key):
        logger.info(
            "ASL deposit alert cooldown'da — xabar yuborilmadi (saldo=%s)", saldo_sum
        )
        return {
            "ok": False,
            "saldo_sum": saldo_sum,
            "cooldown_skip": True,
        }
    # 12 soatlik cooldown — kunda 2 ta xabar (00:00 va 12:00 atrofida)
    _alert_cache.set(cooldown_key, 1, timeout=12 * 60 * 60)

    # Past balans — faqat ROOT_ADMIN'ga signal (self-delete pattern bilan bir xil).
    # WARNING (Fatal emas): operatsion ogohlantirish — to'lov tizimi crash bo'lmadi,
    # to'lovlar shunchaki navbatga turadi. Fatal level haqiqiy fatal'larni yashirardi.
    logger.warning(
        "ASL DEPOZIT PAST: saldo=%s so'm, threshold=%s so'm",
        saldo_sum, threshold,
    )

    title = "ATMOS ASL depoziti past!"
    body = (
        f"Joriy balans: {saldo_sum:,.0f} so'm "
        f"(threshold: {threshold:,.0f} so'm). "
        "Doctor payout'lari to'xtab qolmasligi uchun depozitni to'ldiring."
    )

    notified = False
    try:
        from django.contrib.auth import get_user_model

        from app.notifications.models import Notification
        from app.notifications.utils import notify
        User = get_user_model()

        root_phone = getattr(settings, "ROOT_ADMIN_PHONE", "")
        if not root_phone:
            logger.warning(
                "ASL deposit alert: ROOT_ADMIN_PHONE sozlanmagan, xabar yuborilmadi"
            )
        else:
            root_admin = User.objects.filter(phone=root_phone).first()
            if root_admin:
                # In-app FCM push
                try:
                    notify(
                        root_admin,
                        type=Notification.Type.SYSTEM,
                        title=title,
                        body=body,
                        app_scope="admin",
                        data={"saldo_sum": str(saldo_sum), "threshold": str(threshold)},
                    )
                except Exception as e:
                    logger.warning("Root admin push yuborilmadi: %s", e)

                # Telegram bot xabari
                chat_id = getattr(root_admin, "telegram_chat_id", None)
                if chat_id:
                    try:
                        send_telegram_message(chat_id, f"⚠️ {title}\n\n{body}")
                    except Exception as e:
                        logger.warning("Root admin telegram yuborilmadi: %s", e)

                notified = True
            else:
                logger.warning(
                    "ASL deposit alert: ROOT_ADMIN_PHONE=%s ga mos user topilmadi",
                    root_phone,
                )
    except Exception:
        logger.exception("ASL deposit alert: root admin'ga xabar yuborishda xato")

    return {
        "saldo_sum": saldo_sum,
        "threshold": threshold,
        "low_balance": True,
        "root_admin_notified": notified,
    }
