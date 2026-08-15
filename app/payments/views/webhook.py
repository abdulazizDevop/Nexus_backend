from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


def _alert_admins_money_issue(title: str, detail: str) -> None:
    """"Pul olindi-yu xizmat/yozuv yo'q" — adminlarga Telegram alert (best-effort).

    critical log logda ko'milib qolmasin: mas'ul odam darrov qo'lda refund qilsin.
    Sentry ham (event_level=ERROR) critical'ni event sifatida oladi — occurrence
    count monitoring uchun (son o'ssa avto-refund prioritet bo'ladi).
    """
    from django.conf import settings
    from services.telegram import send_telegram_message

    text = f"🚨 <b>{title}</b>\n\n{detail}"
    for chat_id in getattr(settings, "PAYMENT_ALERT_CHAT_IDS", None) or []:
        try:
            send_telegram_message(chat_id, text)
        except Exception:  # noqa: BLE001
            logger.exception("Payment alert Telegram yuborilmadi chat=%s", chat_id)


def _complete_payment(payment_id: int) -> None:
    """Payment'ni yakunlash + side effect (ProSubscription/Tariff) — Variant B.

    Tartib:
      1) Payment.status = COMPLETED — atomic, race-safe (select_for_update).
         Bu pul olingani manbali yozuv (canonical "money received" mark).
      2) Side effect (subscription/tariff) — alohida atomic transaction'da.
         Idempotent: agar yozuv allaqachon mavjud bo'lsa, qaytadan yaratmaydi.
         Xato bo'lsa — Payment.COMPLETED qaytarilmaydi (provider pulni oldi);
         critical log + Sentry alert orqali admin xabardor bo'ladi va qo'lda
         hal qiladi (plan/tariff'ni qaytarib yaratadi yoki refund).

    Why ikki bosqich: provider bizdan javob kutadi va to'lovni tasdiqlaydi —
    bizning DB qoidalarimiz tufayli "pul olindi-yu yozuv yaratilmadi" stsenariy
    yo'qoladi. Aks holda atomic ichida exception bo'lsa, Payment.PENDING qoladi,
    provider yana retry qiladi va biz har retry'da xato yozamiz.
    """
    # 1-bosqich: status'ni qulflash
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(id=payment_id).first()
        if not payment:
            return
        if payment.status == Payment.Status.COMPLETED:
            # Allaqachon yakunlangan — side effect ham idempotent ishlaydi quyida
            pass
        else:
            # CANCELLED/FAILED holatdan COMPLETED ga o'tish — kech kelgan webhook.
            # Pul haqiqatan olingan, shuning uchun yakunlaymiz, lekin audit/statistik
            # nomuvofiqlik (avval bekor deb sanalgan) uchun aniq log qoldiramiz.
            if payment.status in (
                Payment.Status.CANCELLED,
                Payment.Status.FAILED,
            ):
                logger.warning(
                    "Payment %s RESURRECTED: %s -> COMPLETED (kech webhook). "
                    "user=%s purpose=%s amount=%s provider=%s — audit/reconcile e'tibor bering.",
                    payment.id, payment.status, payment.user_id,
                    payment.purpose, payment.amount, payment.provider,
                )
            payment.status = Payment.Status.COMPLETED
            payment.completed_at = timezone.now()
            payment.save(update_fields=["status", "completed_at"])

    # 2-bosqich: side effect (alohida tranzaksiya, xatosi Payment'ga ta'sir qilmaydi)
    try:
        if payment.purpose == Payment.Purpose.PRO_SUBSCRIPTION:
            _create_pro_subscription(payment)
        elif payment.purpose == Payment.Purpose.DOCTOR_TARIFF:
            _create_tariff_purchase(payment)
        elif payment.purpose == Payment.Purpose.BALANCE_TOPUP:
            _create_balance_topup(payment)
        elif payment.purpose == Payment.Purpose.CONSULTATION:
            _confirm_consultation(payment)
    except Exception:
        logger.critical(
            "Payment %s yakunlandi, lekin side-effect yaratishda xato. "
            "Pul olingan, lekin %s yaratilmagan. Admin qo'lda hal qilishi kerak.",
            payment.id, payment.purpose, exc_info=True,
        )
        _alert_admins_money_issue(
            "To'lov yakunlandi, yozuv yaratilmadi",
            f"Payment #{payment.id} · {payment.amount} so'm · user={payment.user_id}\n"
            f"purpose={payment.purpose} · provider={payment.provider}\n"
            f"Pul olingan, side-effect (obuna/tarif/konsultatsiya) yaratilmagan — qo'lda hal qiling.",
        )
        return

    logger.info(
        "Payment yakunlandi: payment=%s user=%s purpose=%s amount=%s provider=%s txn=%s",
        payment.id,
        payment.user_id,
        payment.purpose,
        payment.amount,
        payment.provider,
        payment.provider_transaction_id,
    )


def _create_pro_subscription(payment: Payment) -> None:
    """Idempotent — agar shu Payment uchun ProSubscription bor bo'lsa, hech narsa qilmaydi.

    OneToOneField tufayli DB unique constraint ham buzilmaydi, lekin biz oldindan
    tekshiramiz — IntegrityError'siz silent return.
    """
    if ProSubscription.objects.filter(payment=payment).exists():
        return  # Idempotent

    plan_id = payment.metadata.get("plan_id")
    plan = ProPlan.objects.filter(id=plan_id).first()
    if not plan:
        # Critical: plan o'chirib tashlangan, lekin pul olindi.
        # Admin qo'lda yangi plan yaratib, ProSubscription yaratishi kerak.
        logger.critical(
            "Payment %s: ProPlan id=%s topilmadi. Plan o'chirib tashlangan? "
            "Pul olingan (amount=%s), obuna yaratilmagan!",
            payment.id, plan_id, payment.amount,
        )
        raise ValueError(f"ProPlan {plan_id} not found for completed Payment {payment.id}")

    now = timezone.now()
    ProSubscription.objects.create(
        user=payment.user,
        plan=plan,
        plan_snapshot=payment.metadata.get("plan_snapshot", {}),
        starts_at=now,
        expires_at=now + timezone.timedelta(days=plan.duration_days),
        payment=payment,
    )


def _create_tariff_purchase(payment: Payment) -> None:
    """Idempotent — DoctorTariffPurchase + DoctorBalance.add_earnings() faqat 1 marta."""

    if DoctorTariffPurchase.objects.filter(payment=payment).exists():
        return  # Idempotent

    tariff_id = payment.metadata.get("tariff_id")
    doctor_id = payment.metadata.get("doctor_id")
    tariff = DoctorTariff.objects.filter(id=tariff_id).first()
    doctor = DoctorProfile.objects.filter(id=doctor_id).first()
    if not tariff or not doctor:
        # Critical: tariff yoki doctor o'chirib tashlangan.
        logger.critical(
            "Payment %s: DoctorTariff id=%s yoki Doctor id=%s topilmadi. "
            "Pul olingan (amount=%s), tarif xaridi yaratilmagan!",
            payment.id, tariff_id, doctor_id, payment.amount,
        )
        raise ValueError(
            f"Tariff/Doctor not found for completed Payment {payment.id}"
        )

    commission_percent = resolve_commission(doctor)
    # Pul aniqligi: komissiyani 2-decimal'ga yaxlitlab, doctor_earnings'ni
    # ayirma orqali hisoblaymiz — shunda commission + earnings == amount_paid
    # invarianti har doim saqlanadi va balance.add_earnings yaxlitlangan
    # qiymatni oladi (DB field decimal_places=2 bilan moslik).
    commission_amount = (payment.amount * commission_percent / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    doctor_earnings = payment.amount - commission_amount

    hold_days = SystemSetting.get_int(PAYOUT_HOLD_DAYS_KEY, PAYOUT_HOLD_DAYS_DEFAULT)

    now = timezone.now()
    DoctorTariffPurchase.objects.create(
        patient=payment.user,
        doctor=doctor,
        tariff=tariff,
        tariff_snapshot=payment.metadata.get("tariff_snapshot", {}),
        starts_at=now,
        expires_at=now + timezone.timedelta(days=tariff.duration_days),
        amount_paid=payment.amount,
        commission_percent=commission_percent,
        commission_amount=commission_amount,
        doctor_earnings=doctor_earnings,
        payment=payment,
        available_at=now + timezone.timedelta(days=hold_days),
    )

    balance, _ = DoctorBalance.objects.get_or_create(doctor=doctor)
    balance.add_earnings(doctor_earnings)

    # Marketplace side-effect: to'lov = avto-ACCEPTED connection + doctor'ga push.
    # Best-effort — bu yerdagi xato pul oqimini BUZMAYDI (purchase+balance allaqachon
    # saqlangan). Idempotent: mavjud connection ham ACCEPTED'ga o'tadi, dublikat yo'q.
    try:
        _auto_connect_after_tariff(payment.user, doctor, tariff)
    except Exception:
        logger.exception(
            "Payment %s: tarif xarididan keyin avto-connect/push xato (pul saqlandi, "
            "connection yaratilmagan bo'lishi mumkin) — bemor=%s doctor=%s",
            payment.id, payment.user_id, doctor.id,
        )


def _ensure_accepted_connection(patient_user, doctor, now) -> bool:
    """doctor↔patient ACCEPTED connection (idempotent upsert) + fresh-connect'da
    toza chat. Push YUBORMAYDI — chaqiruvchi o'ziga mos push yuboradi (tarif yoki
    konsultatsiya). Marketplace ulanish qoidasi bilan (doctor_marketplace_connection.md):
      - (doctor, patient) YO'Q → ACCEPTED yaratiladi (added_by=patient).
      - BOR (pending/accepted/declined) → ACCEPTED'ga, added_by/requested_by
        O'ZGARMAYDI (referral manbasi saqlanadi).
    unique_together(doctor, patient) tufayli update_or_create atomik-idempotent.
    Qaytaradi: was_connected (avval ACCEPTED bo'lganmi — fresh-connect aniqlash uchun).
    """
    prior = DoctorPatient.objects.filter(
        doctor=doctor, patient=patient_user
    ).first()
    was_connected = bool(
        prior and prior.status == DoctorPatient.Status.ACCEPTED
    )
    DoctorPatient.objects.update_or_create(
        doctor=doctor,
        patient=patient_user,
        defaults={
            "status": DoctorPatient.Status.ACCEPTED,
            "responded_at": now,
        },
        create_defaults={
            "status": DoctorPatient.Status.ACCEPTED,
            "responded_at": now,
            "added_by": DoctorPatient.AddedBy.PATIENT,
            "requested_by": DoctorPatient.AddedBy.PATIENT,
        },
    )
    if not was_connected:
        _start_clean_doctor_chat(patient_user, doctor, now)
    return was_connected


def _auto_connect_after_tariff(patient_user, doctor, tariff) -> None:
    """Marketplace: tarif xaridi = ACCEPTED connection + doctor push (tarif nomi bilan).

    Connection yadrosi `_ensure_accepted_connection` (tarif + konsultatsiya reuse);
    bu funksiya faqat tarifga xos push'ni qo'shadi (app_scope=doctor, localized, async).
    """
    now = timezone.now()
    _ensure_accepted_connection(patient_user, doctor, now)

    tariff_name = (
        pick_translation(tariff.name, "uz")
        if isinstance(tariff.name, dict)
        else str(tariff.name or "")
    )
    notify_by_key_user.delay(
        user_id=doctor.user_id,
        type=Notification.Type.CONNECTION_ACCEPTED,
        key="new_patient_marketplace",
        params={
            "name": patient_user.full_name or "Bemor",
            "tariff": tariff_name or "tarif",
        },
        data={
            "doctor_id": str(doctor.id),
            "patient_id": str(patient_user.id),
            "source": "marketplace",
        },
        app_scope="doctor",
    )


def _start_clean_doctor_chat(patient_user, doctor, cutoff) -> None:
    """Fresh connect'da doctor uchun toza chat.

    Mavjud consultation room bo'lsa (bemor marketplace'da AI bilan suhbatlashgan):
      - `doctor_visible_from = cutoff` → doctor xariddan oldingi AI thread'ni
        ko'rmaydi (bemor to'liq tarixni ko'radi);
      - connect system xabari yoziladi — cutoff'dan keyin, shuning uchun doctor
        room ro'yxatida shu toza xabarni birinchi ko'radi.
    Room yo'q bo'lsa (bemor AI bilan yozishmagan) — hech narsa qilinmaydi, kelajakdagi
    room to'liq ko'rinadi. Idempotent: cutoff faqat bir marta (None bo'lsa) qo'yiladi.
    """
    from app.chat.models import ChatRoom, Message

    room = ChatRoom.objects.filter(
        room_type=ChatRoom.RoomType.CONSULTATION,
        doctor=doctor,
        patient__user=patient_user,
    ).first()
    if not room:
        return
    if room.doctor_visible_from is None:
        room.doctor_visible_from = cutoff
        room.save(update_fields=["doctor_visible_from", "updated_at"])
    Message.create_system(
        room,
        "Tarif faollashtirildi — shifokor bilan chat boshlandi.",
        sender=patient_user,
        scope="patient",
    )


def _confirm_consultation(payment: Payment) -> None:
    """Konsultatsiya to'lovi yakunlandi — idempotent (status PENDING_PAYMENT'dan chiqsa qaytadi).

    Tartib:
      - Consultation.status = CONFIRMED + LiveKit room_name tayinlanadi.
      - Doctor balansiga komissiyasiz-qism (tarif kabi; MVP'da hold'siz — darhol available).
      - Avto-connect (ACCEPTED connection + toza chat) — tarif bilan bir yadro.
      - Push: bemorga tasdiq + doctorga yangi konsultatsiya (best-effort).
    """
    from app.doctors.models import Slot
    from app.meetings.models import Consultation
    from services.livekit import generate_room_name

    consultation_id = payment.metadata.get("consultation_id")
    now = timezone.now()

    # Butun tasdiq — Consultation qatorini QULFLAB (select_for_update) atomic'da.
    # Bu (a) parallel dublikat webhook double-credit oldini oladi, (b) expire task
    # bilan poygani serializatsiya qiladi.
    with transaction.atomic():
        consultation = (
            Consultation.objects.select_for_update()
            .select_related("doctor__user", "patient")
            .filter(id=consultation_id)
            .first()
        )
        if not consultation:
            logger.critical(
                "Payment %s: Consultation id=%s topilmadi. Pul olingan (amount=%s), "
                "konsultatsiya tasdiqlanmagan!",
                payment.id, consultation_id, payment.amount,
            )
            raise ValueError(f"Consultation not found for completed Payment {payment.id}")

        st = consultation.status
        # Haqiqiy idempotentlik: allaqachon tasdiqlangan/yakunlangan → jim qaytish OK.
        if st in (Consultation.Status.CONFIRMED, Consultation.Status.COMPLETED):
            return
        # Bekor qilingan-u pul kelgan (kech webhook) — xizmat yo'q, refund kerak.
        if st in (
            Consultation.Status.CANCELLED_BY_PATIENT,
            Consultation.Status.CANCELLED_BY_DOCTOR,
        ):
            logger.critical(
                "Payment %s COMPLETED, lekin Consultation %s BEKOR qilingan (status=%s). "
                "Pul olingan, xizmat yo'q — admin REFUND qilishi kerak.",
                payment.id, consultation.id, st,
            )
            _alert_admins_money_issue(
                "Konsultatsiya: pul olindi, xizmat yo'q (band bekor qilingan)",
                f"Payment #{payment.id} · {payment.amount} so'm · user={payment.user_id}\n"
                f"Consultation #{consultation.id} status={st}\n"
                f"Bemor to'lagan, konsultatsiya bekor — qo'lda REFUND kerak.",
            )
            return
        # Kech to'lov (webhook yo'qolib, reconcile keyin topdi): expire slotni bo'shatgan
        # bo'lishi mumkin. Slotni QAYTA egallashga urinamiz — bo'sh bo'lsa re-book va
        # tasdiqqa o'tamiz; band bo'lsa (boshqa bemor oldi) xizmat berib bo'lmaydi → critical.
        if st == Consultation.Status.EXPIRED:
            slot = (
                Slot.objects.select_for_update()
                .filter(
                    doctor=consultation.doctor,
                    date=consultation.date,
                    start_time=consultation.start_time,
                )
                .first()
            )
            if slot and slot.consultation_id == consultation.id:
                pass  # allaqachon shu konsultatsiyaga bog'langan
            elif slot and slot.status == Slot.Status.FREE:
                slot.status = Slot.Status.BOOKED
                slot.consultation = consultation
                slot.save(update_fields=["status", "consultation", "updated_at"])
            else:
                logger.critical(
                    "Payment %s COMPLETED, lekin Consultation %s EXPIRED va slot band/yo'q. "
                    "Pul olingan, slot boshqa bemorda — admin REFUND/reschedule qilishi kerak.",
                    payment.id, consultation.id,
                )
                _alert_admins_money_issue(
                    "Konsultatsiya: pul olindi, slot band (band muddati o'tган)",
                    f"Payment #{payment.id} · {payment.amount} so'm · user={payment.user_id}\n"
                    f"Consultation #{consultation.id} EXPIRED, slot boshqa bemorda\n"
                    f"Bemor kech to'lagan (eski deeplink) — qo'lda REFUND/reschedule kerak.",
                )
                return

        # Bu yerga: PENDING_PAYMENT yoki EXPIRED(slot qayta egallandi) → TASDIQ.
        doctor = consultation.doctor
        commission_percent = resolve_commission(doctor)
        commission_amount = (payment.amount * commission_percent / Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        doctor_earnings = payment.amount - commission_amount

        consultation.status = Consultation.Status.CONFIRMED
        consultation.payment = payment
        consultation.room_name = consultation.room_name or generate_room_name()
        consultation.save(update_fields=["status", "payment", "room_name", "updated_at"])

        balance, _ = DoctorBalance.objects.get_or_create(doctor=doctor)
        balance.add_earnings(doctor_earnings)

        payment.metadata = {
            **(payment.metadata or {}),
            "commission_percent": str(commission_percent),
            "commission_amount": str(commission_amount),
            "doctor_earnings": str(doctor_earnings),
        }
        payment.save(update_fields=["metadata"])

    # Lock chiqqach (best-effort — pul oqimini buzmaydi): avto-connect + push.
    try:
        _ensure_accepted_connection(consultation.patient, doctor, now)
    except Exception:
        logger.exception(
            "Consultation %s: avto-connect xato (pul saqlandi) bemor=%s doctor=%s",
            consultation.id, consultation.patient_id, doctor.id,
        )

    _notify_consultation_confirmed(consultation)


def _notify_consultation_confirmed(consultation) -> None:
    """Push: bemorga tasdiq + doctorga yangi konsultatsiya. Best-effort."""
    when = f"{consultation.date} {consultation.start_time.strftime('%H:%M')}"
    doctor_name = consultation.doctor.user.full_name or "Shifokor"
    patient_name = consultation.patient.full_name or "Bemor"
    data = {
        "consultation_id": str(consultation.id),
        "doctor_id": str(consultation.doctor_id),
        "date": str(consultation.date),
        "time": consultation.start_time.strftime("%H:%M"),
    }
    try:
        notify(
            consultation.patient,
            type=Notification.Type.CONSULTATION_CONFIRMED,
            title="Konsultatsiya tasdiqlandi",
            body=f"Dr. {doctor_name} bilan {when} da video-konsultatsiya tasdiqlandi.",
            data=data,
            app_scope="patient",
        )
    except Exception:
        logger.exception("Consultation %s: bemorga push xato", consultation.id)
    try:
        notify(
            consultation.doctor.user,
            type=Notification.Type.CONSULTATION_BOOKED,
            title="Yangi konsultatsiya",
            body=f"{patient_name} {when} ga video-konsultatsiya uchun to'lov qildi.",
            data=data,
            app_scope="doctor",
        )
    except Exception:
        logger.exception("Consultation %s: doctorga push xato", consultation.id)


def _create_balance_topup(payment: Payment) -> None:
    """Doctor balansini to'ldirish — idempotent (BalanceTopup OneToOne).

    To'liq summa balansga qo'shiladi (komissiyasiz — doctor o'z puli).
    """
    if BalanceTopup.objects.filter(payment=payment).exists():
        return  # Idempotent

    doctor_id = payment.metadata.get("doctor_profile_id")
    doctor = DoctorProfile.objects.filter(id=doctor_id).first()
    if not doctor:
        # Fallback: to'lovchi user orqali doctor profilni topish.
        doctor = DoctorProfile.objects.filter(user=payment.user).first()
    if not doctor:
        logger.critical(
            "Payment %s: balance_topup uchun DoctorProfile topilmadi "
            "(doctor_profile_id=%s, user=%s). Pul olingan (amount=%s), "
            "balansga qo'shilmagan!",
            payment.id, doctor_id, payment.user_id, payment.amount,
        )
        raise ValueError(
            f"DoctorProfile not found for completed topup Payment {payment.id}"
        )

    BalanceTopup.objects.create(
        doctor=doctor, amount=payment.amount, payment=payment
    )
    balance, _ = DoctorBalance.objects.get_or_create(doctor=doctor)
    balance.add_topup(payment.amount)


# --- Webhook view'lari (paytechuz) ---
# Paytechuz har provider uchun signature/auth ni o'zi tekshiradi va o'zining
# `Transaction` modelida log yuritadi. Bizga faqat Payment'ni yangilash qoladi.
# `transaction.account_id` = Payment.id (PAYTECHUZ.ACCOUNT_FIELD = "id").


def _verify_webhook_amount(payment: Payment, txn) -> bool:
    """Webhook'dagi summa Payment.amount ga aynan teng ekanini tekshiradi.

    Why: provayder yuborgan summa Payment.amount'dan farq qilsa, bu
    underpayment yoki soxta callback signali — yakunlash xavfli (arzon
    to'lov uchun qimmat tarif/Pro berib yuborilishi mumkin). Paytechuz
    `AMOUNT_FIELD` validation'iga (prepare callback'da) qo'shimcha
    defense-in-depth: success callback'da ham tekshirib chiqamiz.
    Audit C6 — barcha 3 provider (Payme/Click/Uzum) endi AMOUNT_FIELD
    bilan tashkillangan, lekin bu funksiya har ehtimolga qarshi qoladi.
    """
    received_raw = getattr(txn, "amount", None)
    try:
        received = (
            Decimal(str(received_raw)) if received_raw is not None else None
        )
    except (InvalidOperation, ValueError, TypeError):
        received = None

    if received is None or received != payment.amount:
        logger.critical(
            "Webhook AMOUNT MISMATCH: payment=%s user=%s expected=%s "
            "received=%r provider=%s txn=%s — yakunlanmadi "
            "(potensial firibgarlik signali)",
            payment.id, payment.user_id, payment.amount, received_raw,
            payment.provider, getattr(txn, "transaction_id", None),
        )
        return False
    return True


def _on_provider_success(provider_name: str, txn) -> None:
    """Provider'dan muvaffaqiyatli to'lov keldi — Payment'ni yakunlash.

    `txn` — paytechuz Transaction instance (account_id, amount, transaction_id).
    """
    provider_txn_id = getattr(txn, "transaction_id", None)
    logger.info(
        "Webhook SUCCESS keldi: provider=%s account_id=%s txn=%s",
        provider_name, txn.account_id, provider_txn_id,
    )

    payment = Payment.objects.filter(id=txn.account_id).first()
    if not payment:
        logger.warning(
            "Webhook: Payment topilmadi provider=%s account_id=%s",
            provider_name,
            txn.account_id,
        )
        return

    if not _verify_webhook_amount(payment, txn):
        return

    if provider_txn_id and payment.provider_transaction_id != provider_txn_id:
        payment.provider_transaction_id = provider_txn_id
        payment.save(update_fields=["provider_transaction_id"])

    _complete_payment(payment.id)


def _on_provider_cancel(provider_name: str, txn) -> None:
    """Provider to'lovni bekor qildi — Payment statusini yangilash.

    `provider_transaction_id` ni audit uchun saqlaymiz — keyinchalik provider
    tomondan reconciliation kerak bo'lganda kerak bo'ladi.
    """
    provider_txn_id_log = getattr(txn, "transaction_id", None)
    logger.info(
        "Webhook CANCEL keldi: provider=%s account_id=%s txn=%s",
        provider_name, txn.account_id, provider_txn_id_log,
    )

    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update().filter(id=txn.account_id).first()
        )
        if not payment:
            logger.warning(
                "Webhook cancel: Payment topilmadi provider=%s account_id=%s",
                provider_name, txn.account_id,
            )
            return
        if payment.status == Payment.Status.COMPLETED:
            # Yakunlangan to'lovni bekor qilmaymiz — refund alohida flow.
            logger.warning(
                "Webhook cancel keldi, lekin payment yakunlangan: provider=%s id=%s",
                provider_name,
                payment.id,
            )
            return

        update_fields = ["status"]
        provider_txn_id = getattr(txn, "transaction_id", None)
        if provider_txn_id and payment.provider_transaction_id != provider_txn_id:
            payment.provider_transaction_id = provider_txn_id
            update_fields.append("provider_transaction_id")

        payment.status = Payment.Status.CANCELLED
        payment.save(update_fields=update_fields)
        logger.info(
            "Payment bekor qilindi: provider=%s payment=%s user=%s amount=%s",
            provider_name, payment.id, payment.user_id, payment.amount,
        )



def _log_webhook_response(provider_name: str, response) -> None:
    """Provider'ga qaytariladigan javobni log'ga yozadi.

    Click/Uzum javobida `error` < 0 bo'lsa xato (Click API: -1, -2, -3, ...).
    Payme javobida `error: {code: -31xxx, message: ...}` bo'lsa xato.
    HTTP status >= 400 ham xato deb qabul qilinadi.
    """
    try:
        body = getattr(response, "content", b"")
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        status_code = getattr(response, "status_code", None)

        is_error = False

        # HTTP status >= 400 → xato
        if isinstance(status_code, int) and status_code >= 400:
            is_error = True

        # JSON body'dan error'ni tekshirish
        try:
            import json
            parsed = json.loads(body) if body else {}
        except (ValueError, TypeError):
            parsed = {}

        if isinstance(parsed, dict):
            err = parsed.get("error")
            # Payme — error: {"code": -31xxx, "message": "..."}
            if isinstance(err, dict):
                if err.get("code") is not None:
                    is_error = True
            # Click/Uzum — error: -2 (int) yoki "-2" (string)
            elif err is not None:
                try:
                    if int(err) < 0:
                        is_error = True
                except (ValueError, TypeError):
                    pass

        log_fn = logger.warning if is_error else logger.info
        log_fn(
            "%s webhook response: status=%s body=%s",
            provider_name.capitalize(), status_code, body[:500] if isinstance(body, str) else body,
        )
    except Exception:
        # Loglash kodi hech qachon flow'ni buzmasligi kerak
        logger.exception("Webhook response log yozishda kutilmagan xato (%s)", provider_name)


class _ProviderWebhookMixin:
    """Payme/Click/Uzum webhook view'lar uchun umumiy logika.

    Uchala provider bir xil ish qiladi: POST'ni loglash, paytechuz base
    view'iga uzatish, javobni loglash; success/cancel callback'larda
    Payment'ni yakunlash/bekor qilish. Faqat `provider_name` farq qiladi
    (Uzum qo'shimcha confirm-strip hook'ini `post` override qiladi).
    """

    provider_name: str = ""

    def post(self, request, *args, **kwargs):
        logger.info(
            "%s webhook POST keldi: ip=%s body=%s",
            self.provider_name, request.META.get("REMOTE_ADDR"), request.body[:500],
        )
        response = super().post(request, *args, **kwargs)
        _log_webhook_response(self.provider_name, response)
        return response

    def successfully_payment(self, params, transaction):
        logger.info(
            "%s successfully_payment: params=%s txn=%s account_id=%s",
            self.provider_name, params,
            getattr(transaction, "transaction_id", None),
            getattr(transaction, "account_id", None),
        )
        _on_provider_success(self.provider_name, transaction)

    def cancelled_payment(self, params, transaction):
        logger.info(
            "%s cancelled_payment: params=%s txn=%s account_id=%s",
            self.provider_name, params,
            getattr(transaction, "transaction_id", None),
            getattr(transaction, "account_id", None),
        )
        _on_provider_cancel(self.provider_name, transaction)


class PaymeWebhookView(_ProviderWebhookMixin, BasePaymeWebhookView):
    provider_name = "payme"


class ClickWebhookView(_ProviderWebhookMixin, BaseClickWebhookView):
    provider_name = "click"
