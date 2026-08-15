"""Push/in-app notification matnlari katalogi.

Har bir notification turi `key` orqali ochiladi va foydalanuvchining
`UserSettings.language` (uz/ru/cyr) ga qarab tegishli matn tanlanadi.

Foydalanish:
    from app.notifications.utils import notify_by_key

    notify_by_key(
        user=patient,
        type=Notification.Type.APPOINTMENT_APPROVED,
        key="appointment_approved",
        params={"doctor_name": "Dr. Karimov", "time": "14:30"},
        app_scope="patient",
    )

`params` body matn'idagi `{placeholder}` larni `.format(**params)` bilan
to'ldiradi. Title odatda parametrsiz.

Yangi notification qo'shish:
1. Shu yerga `key` qo'shing (3 til bilan).
2. Call site'da `notify_by_key(key="...")` ishlating.
3. Eski `title=..., body=...` ishlatish ham ishlaydi (backward compat).
"""

# Bo'sh stringlar — tegishli tilda hali tarjima qo'shilmagan. fallback uz.
NOTIFY_CATALOG: dict[str, dict[str, dict[str, str]]] = {
    # === Meetings (uchrashuvlar) ===
    "appointment_request": {
        "title": {
            "uz": "Yangi qabul so'rovi",
            "ru": "Новый запрос на приём",
            "cyr": "Янги қабул сўрови",
        },
        "body": {
            "uz": "{name} {date} {time} ga qabul so'radi",
            "ru": "{name} запрашивает приём на {date} в {time}",
            "cyr": "{name} {date} {time} га қабул сўради",
        },
    },
    "appointment_approved": {
        "title": {
            "uz": "Qabul tasdiqlandi",
            "ru": "Приём подтверждён",
            "cyr": "Қабул тасдиқланди",
        },
        "body": {
            "uz": "Dr. {doctor_name} qabulingizni {date} {time} ga tasdiqladi",
            "ru": "Доктор {doctor_name} подтвердил приём на {date} в {time}",
            "cyr": "Dr. {doctor_name} қабулингизни {date} {time} га тасдиқлади",
        },
    },
    "appointment_rejected": {
        "title": {
            "uz": "Qabul rad etildi",
            "ru": "Приём отклонён",
            "cyr": "Қабул рад этилди",
        },
        "body": {
            "uz": "Dr. {doctor_name}: {reason}",
            "ru": "Доктор {doctor_name}: {reason}",
            "cyr": "Dr. {doctor_name}: {reason}",
        },
    },
    "review_request": {
        "title": {
            "uz": "Sharhingiz kerak",
            "ru": "Оставьте отзыв",
            "cyr": "Шарҳингиз керак",
        },
        "body": {
            "uz": "Dr. {doctor_name} bilan qabul yakunlandi — sharh qoldiring",
            "ru": "Приём с доктором {doctor_name} завершён — оставьте отзыв",
            "cyr": "Dr. {doctor_name} билан қабул якунланди — шарҳ қолдиринг",
        },
    },
    # === Feedbacks (sharhlar) ===
    "new_review": {
        "title": {
            "uz": "Yangi sharh keldi",
            "ru": "Новый отзыв",
            "cyr": "Янги шарҳ келди",
        },
        "body": {
            "uz": "{stars} — yangi sharh",
            "ru": "{stars} — новый отзыв",
            "cyr": "{stars} — янги шарҳ",
        },
    },
    "new_review_with_comment": {
        "title": {
            "uz": "Yangi sharh keldi",
            "ru": "Новый отзыв",
            "cyr": "Янги шарҳ келди",
        },
        "body": {
            "uz": "{stars} — {snippet}",
            "ru": "{stars} — {snippet}",
            "cyr": "{stars} — {snippet}",
        },
    },
    # === Chat / Calls ===
    "missed_call": {
        "title": {
            "uz": "Javobsiz qo'ng'iroq",
            "ru": "Пропущенный звонок",
            "cyr": "Жавобсиз қўнғироқ",
        },
        "body": {
            "uz": "{name} javob bermadi",
            "ru": "{name} не ответил",
            "cyr": "{name} жавоб бермади",
        },
    },
    "incoming_call": {
        "title": {
            "uz": "Kiruvchi qo'ng'iroq",
            "ru": "Входящий звонок",
            "cyr": "Кирувчи қўнғироқ",
        },
        "body": {
            "uz": "{name} {call_type} qo'ng'iroq qilmoqda",
            "ru": "{name} звонит ({call_type})",
            "cyr": "{name} {call_type} қўнғироқ қилмоқда",
        },
    },
    # === Doctor-Patient connection ===
    "connection_request": {
        "title": {
            "uz": "Yangi bog'lanish so'rovi",
            "ru": "Новый запрос на связь",
            "cyr": "Янги боғланиш сўрови",
        },
        "body": {
            "uz": "{name} sizga bog'lanish so'rovi yubordi",
            "ru": "{name} отправил(а) вам запрос на связь",
            "cyr": "{name} сизга боғланиш сўрови юборди",
        },
    },
    "connection_accepted": {
        "title": {
            "uz": "Bog'lanish qabul qilindi",
            "ru": "Запрос на связь принят",
            "cyr": "Боғланиш қабул қилинди",
        },
        "body": {
            "uz": "{name} sizning so'rovingizni qabul qildi",
            "ru": "{name} принял(а) ваш запрос",
            "cyr": "{name} сизнинг сўровингизни қабул қилди",
        },
    },
    "connection_declined": {
        "title": {
            "uz": "Bog'lanish rad etildi",
            "ru": "Запрос на связь отклонён",
            "cyr": "Боғланиш рад этилди",
        },
        "body": {
            "uz": "{name} sizning so'rovingizni rad etdi",
            "ru": "{name} отклонил(а) ваш запрос",
            "cyr": "{name} сизнинг сўровингизни рад этди",
        },
    },
    "new_patient_marketplace": {
        "title": {
            "uz": "Yangi bemor",
            "ru": "Новый пациент",
            "cyr": "Янги бемор",
        },
        "body": {
            "uz": "{name} \"{tariff}\" tarifini sotib oldi",
            "ru": "{name} приобрёл(а) тариф «{tariff}»",
            "cyr": "{name} \"{tariff}\" тарифини сотиб олди",
        },
    },
    "support_reply": {
        "title": {
            "uz": "Qo'llab-quvvatlash javobi",
            "ru": "Ответ поддержки",
            "cyr": "Қўллаб-қувватлаш жавоби",
        },
        "body": {
            "uz": "{sender_name}: {snippet}",
            "ru": "{sender_name}: {snippet}",
            "cyr": "{sender_name}: {snippet}",
        },
    },
    # === Payments / Tariffs ===
    "tariff_approved": {
        "title": {
            "uz": "Tarif tasdiqlandi",
            "ru": "Тариф подтверждён",
            "cyr": "Тариф тасдиқланди",
        },
        "body": {
            "uz": '"{tariff_name}" tarifingiz tasdiqlandi va sotuvga chiqdi',
            "ru": 'Ваш тариф "{tariff_name}" подтверждён и выставлен на продажу',
            "cyr": '"{tariff_name}" тарифингиз тасдиқланди ва сотувга чиқди',
        },
    },
    "tariff_rejected": {
        "title": {
            "uz": "Tarif rad etildi",
            "ru": "Тариф отклонён",
            "cyr": "Тариф рад этилди",
        },
        "body": {
            "uz": '"{tariff_name}": {reason}',
            "ru": '"{tariff_name}": {reason}',
            "cyr": '"{tariff_name}": {reason}',
        },
    },
    "payout_approved": {
        "title": {
            "uz": "Pul kartangizga o'tkazildi",
            "ru": "Деньги переведены на карту",
            "cyr": "Пул картангизга ўтказилди",
        },
        "body": {
            "uz": "{amount} miqdor kartangizga o'tkazildi",
            "ru": "{amount} переведено на вашу карту",
            "cyr": "{amount} миқдор картангизга ўтказилди",
        },
    },
    "payout_rejected": {
        "title": {
            "uz": "Pul yechish so'rovi rad etildi",
            "ru": "Запрос на вывод отклонён",
            "cyr": "Пул ечиш сўрови рад этилди",
        },
        "body": {
            "uz": "{reason}",
            "ru": "{reason}",
            "cyr": "{reason}",
        },
    },
    "pro_subscription_expired": {
        "title": {
            "uz": "Pro obuna tugadi",
            "ru": "Pro-подписка завершена",
            "cyr": "Pro обуна тугади",
        },
        "body": {
            "uz": "Pro obunangiz bugun tugadi. Davom ettirish uchun yangilang.",
            "ru": "Ваша Pro-подписка завершилась. Продлите для продолжения.",
            "cyr": "Pro обунангиз бугун тугади. Давом эттириш учун янгиланг.",
        },
    },
    # === Treatment (muolaja) ===
    "treatment_reminder": {
        "title": {
            "uz": "⏰ {title}",
            "ru": "⏰ {title}",
            "cyr": "⏰ {title}",
        },
        # body call site'da yig'ilgan (type_display + dosage + vaqt)
        # type_display TextChoices verbose'idan keladi - mobile o'zi tarjima
        # qiladi (admin panel pattern bilan bir xil).
        "body": {
            "uz": "{summary}",
            "ru": "{summary}",
            "cyr": "{summary}",
        },
    },
    # === Medical (analiz) ===
    "analysis_assigned": {
        "title": {
            "uz": "Sizga analiz tayinlandi",
            "ru": "Вам назначен анализ",
            "cyr": "Сизга анализ тайинланди",
        },
        "body": {
            "uz": "{type_name} — {deadline} gacha topshiring",
            "ru": "{type_name} — сдайте до {deadline}",
            "cyr": "{type_name} — {deadline} гача топширинг",
        },
    },
    "analysis_deadline_reminder": {
        "title": {
            "uz": "Analiz topshirish muddati yaqinlashdi",
            "ru": "Срок сдачи анализа близится",
            "cyr": "Анализ топшириш муддати яқинлашди",
        },
        "body": {
            "uz": "{type_name} — {hours} soat qoldi",
            "ru": "{type_name} — осталось {hours} часов",
            "cyr": "{type_name} — {hours} соат қолди",
        },
    },
    "analysis_overdue": {
        "title": {
            "uz": "Analiz topshirilmagan",
            "ru": "Анализ не сдан",
            "cyr": "Анализ топширилмаган",
        },
        "body": {
            "uz": "{type_name} — muddati o'tdi, iltimos shifokorga aytib qo'ying",
            "ru": "{type_name} — срок прошёл, сообщите врачу",
            "cyr": "{type_name} — муддати ўтди, илтимос шифокорга айтиб қўйинг",
        },
    },
    "analysis_submitted": {
        "title": {
            "uz": "Bemor analiz natijasini yukladi",
            "ru": "Пациент загрузил результат анализа",
            "cyr": "Бемор анализ натижасини юклади",
        },
        "body": {
            "uz": "{patient_name} • {type_name}",
            "ru": "{patient_name} • {type_name}",
            "cyr": "{patient_name} • {type_name}",
        },
    },
    "analysis_cancelled_by_doctor": {
        "title": {
            "uz": "Analiz bekor qilindi",
            "ru": "Анализ отменён",
            "cyr": "Анализ бекор қилинди",
        },
        "body": {
            "uz": "{type_name} — shifokor bekor qildi",
            "ru": "{type_name} — отменено врачом",
            "cyr": "{type_name} — шифокор бекор қилди",
        },
    },
    "analysis_cancelled_by_patient": {
        "title": {
            "uz": "Bemor analizni bekor qildi",
            "ru": "Пациент отменил анализ",
            "cyr": "Бемор анализни бекор қилди",
        },
        "body": {
            "uz": "{patient_name} • {type_name}",
            "ru": "{patient_name} • {type_name}",
            "cyr": "{patient_name} • {type_name}",
        },
    },
    "analysis_reviewed": {
        "title": {
            "uz": "Analiz uchun sharh keldi",
            "ru": "Анализ прокомментирован",
            "cyr": "Анализ учун шарҳ келди",
        },
        "body": {
            "uz": "{type_name} — {verdict_preview}",
            "ru": "{type_name} — {verdict_preview}",
            "cyr": "{type_name} — {verdict_preview}",
        },
    },
    "analysis_received": {
        "title": {
            "uz": "Bemor sizga analiz yubordi",
            "ru": "Пациент прислал анализ",
            "cyr": "Бемор сизга анализ юборди",
        },
        "body": {
            "uz": "{patient_name} • {type_name}",
            "ru": "{patient_name} • {type_name}",
            "cyr": "{patient_name} • {type_name}",
        },
    },
}


SUPPORTED_LANGS_FALLBACK = ("uz", "ru", "cyr")


def get_template(key: str, lang: str) -> tuple[str, str]:
    """Catalogdan kalit + til bo'yicha (title, body) shablonini qaytaradi.

    Til topilmasa fallback `uz`, kalit topilmasa ("", "").
    """
    entry = NOTIFY_CATALOG.get(key)
    if not entry:
        return "", ""

    def pick(field: str) -> str:
        bucket = entry.get(field) or {}
        return bucket.get(lang) or bucket.get("uz") or next(iter(bucket.values()), "")

    return pick("title"), pick("body")


def render(key: str, lang: str, params: dict | None = None) -> tuple[str, str]:
    """Catalogdan kalit + til + parametrlar bilan ready-to-send (title, body)."""
    title_tpl, body_tpl = get_template(key, lang)
    params = params or {}
    try:
        title = title_tpl.format(**params) if title_tpl else ""
        body = body_tpl.format(**params) if body_tpl else ""
    except (KeyError, IndexError):
        # Yetishmagan placeholder — fallback: shablon o'zicha
        title = title_tpl
        body = body_tpl
    return title, body
