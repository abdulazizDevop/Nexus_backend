from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar
from .common import _contact_keyboard, _get_admin_contact_text, _get_user_telegram_chat_id, _is_valid_doctor_referral, _referral_skip_keyboard, _send_otp_message, _sex_keyboard, _user_exists_by_phone, _validate_contact  # underscore (star bermaydi)

@router.message(CommandStart(deep_link=True))
async def start_deeplink(message: Message, command: CommandObject, state: FSMContext):
    """Unified deeplink — auth_<role>_<phone>.

    Bot DB tekshirib, mavjud user uchun login flow'ini, yangi user uchun ro'yxatga
    olish flow'ini boshlaydi. Frontend ikkalasini ham bilmaydi.
    """
    args = command.args or ""

    if not args.startswith("auth_"):
        await message.answer(
            "👋 Mediik botiga xush kelibsiz!\n\n"
            "Kirish yoki ro'yxatdan o'tish uchun ilovadan foydalaning."
        )
        return

    parts = args.split("_", 2)
    if len(parts) != 3:
        await message.answer("❌ Noto'g'ri havola. Ilovadan qaytadan urinib ko'ring.")
        return

    role = parts[1]
    raw_phone = parts[2]

    if role not in ("patient", "doctor"):
        await message.answer("❌ Noto'g'ri havola.")
        return

    phone = normalize_phone(raw_phone)
    chat_id = message.chat.id

    if await _user_exists_by_phone(phone):
        # Mavjud user — agar shu Telegram allaqachon bog'langan bo'lsa
        # kontakt qayta talab qilmaymiz, darrov OTP yuboramiz (UX win).
        # Aks holda (boshqa Telegram yoki hali link qilinmagan) — kontakt verify.
        linked_chat_id = await _get_user_telegram_chat_id(phone)
        if linked_chat_id == chat_id:
            otp = await sync_to_async(OTPCode.generate)(
                phone=phone, purpose="login", telegram_chat_id=chat_id
            )
            await _send_otp_message(
                message, state, chat_id, otp,
                header="🔐 <b>Akkauntingizga kirish.</b>",
                code_label="Kodingiz",
            )
            return

        # Yangi Telegram yoki hali bog'lanmagan — kontakt verify
        await state.set_state(AuthStates.waiting_login_contact)
        await state.update_data(phone=phone, role=role, chat_id=chat_id)
        await message.answer(
            "🔐 <b>Akkauntiz mavjud — kirishga tayyormiz.</b>\n\n"
            "Telefoningizni tasdiqlash uchun «Kontaktni ulashish» tugmasini "
            "bosing. So'ng tasdiqlash kodi shu chatda yuboriladi.",
            parse_mode="HTML",
            reply_markup=_contact_keyboard(),
        )
        return

    # Yangi user — ism → kontakt → register OTP
    await state.set_state(AuthStates.waiting_register_name)
    await state.update_data(phone=phone, role=role, chat_id=chat_id)
    await message.answer(
        f"📱 Telefon: {phone}\n\n"
        "👤 Akkauntingiz topilmadi — yangi ro'yxatga olamiz.\n"
        "Iltimos, to'liq ismingizni kiriting:"
    )

@router.message(CommandStart())
async def start_no_args(message: Message):
    """Oddiy /start — deeplinksiz."""
    await message.answer(
        "👋 Mediik botiga xush kelibsiz!\n\n"
        "Kirish yoki ro'yxatdan o'tish uchun ilovadan foydalaning."
    )

@router.message(AuthStates.waiting_login_contact, F.contact)
async def receive_login_contact(message: Message, state: FSMContext):
    """Mavjud user — kontakt tasdiqlandi → login OTP."""
    result = await _validate_contact(message, state)
    if result is None:
        return
    phone, _role, chat_id = result

    otp = await sync_to_async(OTPCode.generate)(
        phone=phone,
        purpose="login",
        telegram_chat_id=chat_id,
    )

    await _send_otp_message(
        message, state, chat_id, otp, header="✅ Telefon tasdiqlandi!"
    )

@router.message(AuthStates.waiting_register_name, F.text)
async def receive_register_name(message: Message, state: FSMContext):
    """Yangi user — ism qabul qilish.

    Keyingi qadam — har doim jins tanlash (inline button).
    """
    full_name = message.text.strip()

    if len(full_name) < 2:
        await message.answer("❌ Ism juda qisqa. Qaytadan kiriting:")
        return

    await state.update_data(full_name=full_name)
    safe_name = html.escape(full_name)

    await state.set_state(AuthStates.waiting_register_sex)
    await message.answer(
        f"✅ Rahmat, {safe_name}!\n\n"
        "👤 Iltimos, jinsingizni tanlang:",
        parse_mode="HTML",
        reply_markup=_sex_keyboard(),
    )

@router.callback_query(AuthStates.waiting_register_sex, F.data.startswith("sex:"))
async def receive_register_sex(callback: CallbackQuery, state: FSMContext):
    """Jins tanlandi → doctor bo'lsa referral code so'rash (skip tugmasi bilan),
    aks holda darrov kontaktga o'tish."""
    sex = callback.data.split(":", 1)[1]
    if sex not in ("male", "female"):
        await callback.answer("❌ Noto'g'ri qiymat", show_alert=True)
        return

    await state.update_data(sex=sex)
    await callback.answer()  # spinner'ni to'xtatish

    data = await state.get_data()
    role = data.get("role", "patient")

    sex_label = "👨 Erkak" if sex == "male" else "👩 Ayol"
    # Inline tugma sahifasini almashtiramiz (jismsiz aniqlik uchun)
    try:
        await callback.message.edit_text(
            f"{callback.message.text or ''}\n\n✅ Tanlandi: {sex_label}",
        )
    except Exception:
        pass

    if role == "doctor":
        await state.set_state(AuthStates.waiting_register_referral)
        await callback.message.answer(
            "🩺 Shifokor sifatida ro'yxatdan o'tyapsiz.\n\n"
            "Agar sizni Mediik tizimiga taklif qilgan seller yoki shifokorning "
            "<b>8 belgili referral kodi</b> bo'lsa, kiriting.\n\n"
            "Bo'lmasa <b>O'tkazib yuborish</b> tugmasini bosing — keyin admin "
            "tasdiqlaganidan keyin ham ishlash mumkin.",
            parse_mode="HTML",
            reply_markup=_referral_skip_keyboard(),
        )
        return

    await state.set_state(AuthStates.waiting_register_contact)
    await callback.message.answer(
        "📱 Endi telefoningizni tasdiqlash uchun quyidagi tugmani bosing.\n\n"
        "⚠️ Faqat «Kontaktni ulashish» tugmasini bosing — "
        "raqamni qo'lda yozmang.",
        reply_markup=_contact_keyboard(),
    )

async def _proceed_to_contact(message: Message, state: FSMContext):
    """Doctor: referral qadamidan keyin — kontakt so'rash qadami."""
    await state.set_state(AuthStates.waiting_register_contact)
    await message.answer(
        "📱 Endi telefoningizni tasdiqlash uchun quyidagi tugmani bosing.",
        reply_markup=_contact_keyboard(),
    )


@router.callback_query(AuthStates.waiting_register_referral, F.data == "ref:skip")
async def skip_register_referral(callback: CallbackQuery, state: FSMContext):
    """Doctor referral'ni o'tkazib yuborish — keyin kontaktga."""
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"{callback.message.text or ''}\n\n⏭ Referral code o'tkazildi"
        )
    except Exception:
        pass
    await _proceed_to_contact(callback.message, state)

@router.message(AuthStates.waiting_register_referral, F.text)
async def receive_register_referral(message: Message, state: FSMContext):
    """Doctor — referral code qabul qilish → validate → kontakt so'rash."""
    code = message.text.strip().upper()

    if not code or len(code) > 20:
        await message.answer(
            "❌ Referral code noto'g'ri formatda. Iltimos, qaytadan kiriting "
            "yoki yuqoridagi <b>O'tkazib yuborish</b> tugmasini bosing:",
            parse_mode="HTML",
        )
        return

    if not await _is_valid_doctor_referral(code):
        admin_info = await _get_admin_contact_text()
        await message.answer(
            "❌ <b>Referral code topilmadi.</b>\n\n"
            "Kod faqat seller yoki tasdiqlangan shifokor tomonidan beriladi. "
            "Iltimos, qaytadan kiriting, <b>O'tkazib yuborish</b> tugmasini "
            "bosing yoki adminlar bilan bog'laning:\n\n"
            f"{admin_info}",
            parse_mode="HTML",
        )
        return

    await state.update_data(referral_code=code)
    await message.answer(
        f"✅ Referral code tasdiqlandi: <code>{code}</code>",
        parse_mode="HTML",
    )
    await _proceed_to_contact(message, state)

@router.message(AuthStates.waiting_register_contact, F.contact)
async def receive_register_contact(message: Message, state: FSMContext):
    """Yangi user — kontakt tasdiqlandi → register OTP."""
    result = await _validate_contact(message, state)
    if result is None:
        return
    phone, role, chat_id = result

    data = await state.get_data()
    full_name = data.get("full_name", "")
    referral_code = data.get("referral_code", "")
    sex = data.get("sex", "")

    # Race himoyasi: ism kiritish va kontakt orasida boshqa qurilmadan
    # ro'yxat ochilgan bo'lishi mumkin — login flow'iga o'tkazamiz.
    if await _user_exists_by_phone(phone):
        otp = await sync_to_async(OTPCode.generate)(
            phone=phone, purpose="login", telegram_chat_id=chat_id
        )
        await _send_otp_message(
            message, state, chat_id, otp,
            header="ℹ️ Akkauntingiz hozirgina tayyor bo'ldi.",
            code_label="Kirish kodingiz",
        )
        return

    otp = await sync_to_async(OTPCode.generate)(
        phone=phone,
        purpose="register",
        full_name=full_name,
        role=role,
        telegram_chat_id=chat_id,
        referral_code=referral_code,
        sex=sex,
    )

    await _send_otp_message(
        message, state, chat_id, otp, header="✅ Telefon tasdiqlandi!"
    )

@router.message(AuthStates.waiting_login_contact)
@router.message(AuthStates.waiting_register_contact)
async def contact_text_fallback(message: Message, state: FSMContext):
    """Kontakt o'rniga matn yuborilsa — qaytadan tugma ko'rsatamiz."""
    await message.answer(
        "⚠️ Iltimos, raqamni qo'lda yozmang.\n\n"
        "Quyidagi «📱 Kontaktni ulashish» tugmasini bosing.\n"
        "Bu orqali Telegram raqamingiz avtomatik tekshiriladi.",
        reply_markup=_contact_keyboard(),
    )

@router.callback_query(F.data.startswith("dose:"))
async def handle_dose_taken(callback: CallbackQuery):
    """Dori eslatmasidagi '✅ Bajardim' bosilganda — o'sha slotni bajarildi deb belgilaydi.

    callback_data: "dose:{treatment_id}:{epoch}". Telegram user → telegram_chat_id orqali
    Django User'ga bog'lanadi; egasi tekshiriladi; slot per-slot completed bo'ladi; xabar
    yangilanadi (tugma olib tashlanadi).
    """
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        treatment_id, epoch = int(parts[1]), int(parts[2])
    except ValueError:
        await callback.answer()
        return

    from app.treatment.telegram_actions import mark_dose_from_telegram

    result = await sync_to_async(mark_dose_from_telegram)(
        callback.from_user.id, treatment_id, epoch
    )

    if result in ("ok", "already"):
        await callback.answer(
            "✅ Bajarildi deb belgilandi" if result == "ok" else "Allaqachon belgilangan ✅"
        )
        # Xabarni yangilaymiz: "bajarilmagan" → "bajarildi", tugmani olib tashlaymiz.
        base = callback.message.text or ""
        if "⏳ Holat: bajarilmagan" in base:
            new_text = base.replace("⏳ Holat: bajarilmagan", "✅ Holat: bajarildi")
        else:
            new_text = f"{base}\n\n✅ Bajarildi"
        try:
            await callback.message.edit_text(new_text, reply_markup=None)
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
    else:
        await callback.answer("❌ Belgilab bo'lmadi", show_alert=True)
