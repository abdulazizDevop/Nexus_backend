from .common import *  # noqa: F401,F403 - umumiy importlar + konstantalar


@shared_task(base=BaseTask, bind=True, name="payments.notify_expired_subscriptions")
def notify_expired_subscriptions(self):
    """Muddati bugun tugagan Pro obunalar haqida bildirishnoma yuboradi."""
    now = timezone.now()
    today = now.date()

    # Pro obunalar
    expired_pro = ProSubscription.objects.filter(
        expires_at__date=today,
    ).select_related("user") # catalog'dan user tilida
    from app.notifications.catalog import render as _render_notif

    for sub in expired_pro:
        chat_id = getattr(sub.user, "telegram_chat_id", None)
        if chat_id:
            try:
                lang = (
                    getattr(getattr(sub.user, "settings", None), "language", None)
                    or "uz"
                )
                _, body = _render_notif("pro_subscription_expired", lang)
                send_telegram_message(chat_id, f"⏰ {body}")
            except Exception as e:
                logger.warning(f"Failed to notify user {sub.user_id}: {e}")

    # Doctor tariflari
    expired_tariffs = DoctorTariffPurchase.objects.filter(
        expires_at__date=today,
    ).select_related("patient", "doctor__user")

    # Tariff expired ham catalog'ga qo'shilsa yaxshi - hozircha doctor_name
    # dynamic, lekin tarjima qilinmagan. TODO: yangi key `tariff_expired_patient`.
    _tariff_expired_msg = {
        "uz": "⏰ {doctor_name} bilan nazorat tarifi bugun tugadi.",
        "ru": "⏰ Тариф наблюдения с {doctor_name} сегодня завершился.",
        "cyr": "⏰ {doctor_name} билан назорат тарифи бугун тугади.",
    }
    for purchase in expired_tariffs:
        chat_id = getattr(purchase.patient, "telegram_chat_id", None)
        if chat_id:
            try:
                lang = (
                    getattr(getattr(purchase.patient, "settings", None), "language", None)
                    or "uz"
                )
                doctor_name = purchase.doctor.user.full_name or "shifokor"
                template = _tariff_expired_msg.get(lang) or _tariff_expired_msg["uz"]
                send_telegram_message(chat_id, template.format(doctor_name=doctor_name))
            except Exception as e:
                logger.warning(f"Failed to notify patient {purchase.patient_id}: {e}")

    return {
        "pro_expired": expired_pro.count(),
        "tariffs_expired": expired_tariffs.count(),
    }


