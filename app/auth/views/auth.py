from .common import *  # noqa: F401,F403
from .common import _REGISTRATION_TOKEN_SALT,_REGISTRATION_TOKEN_TTL_SEC,_is_valid_doctor_referral,_link_telegram_chat,_send_sms_otp_response,_user_payload


@extend_schema(tags=["Auth"])
class AuthViewSet(viewsets.ViewSet):
    """Telegram OTP orqali autentifikatsiya"""

    permission_classes = [AllowAny]

    def get_permissions(self):
        if self.action == "logout":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_serializer_class(self):
        actions = {
            "auth": AuthRequestSerializer,
            "auth_verify": AuthVerifySerializer,
            "complete_registration": CompleteRegistrationSerializer,
            "logout": LogoutSerializer,
        }
        return actions.get(self.action, AuthRequestSerializer)

    def get_serializer(self, *args, **kwargs):
        return self.get_serializer_class()(*args, **kwargs)

    @extend_schema(
        request=AuthRequestSerializer,
        summary="Auth — telefon yuborish (register yoki login)",
        description=(
            "Yagona auth endpoint. Ikki kanal: SMS va Telegram bot.\n\n"
            "**LOGIN (mavjud user):**\n"
            "- Telegram bog'langan + `channel != 'sms'`: Telegram orqali OTP\n"
            "- Aks holda yoki `channel='sms'`: SMS orqali OTP (Eskiz)\n\n"
            "**REGISTER (yangi user):**\n"
            "- `channel='sms'`: SMS register — `full_name` majburiy, doctor "
            "uchun `referral_code` ham. Backend validate qilib OTP yuboradi.\n"
            "- Default: bot deeplink (ism + kontakt + referral bot ichida)\n\n"
            "**Test user (99800...):** DEFAULT_OTP_CODE bilan kirish."
        ),
    )
    @action(detail=False, methods=["post"], url_path="auth")
    def auth(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone"]
        role = serializer.validated_data.get("role", "patient")
        channel = (serializer.validated_data.get("channel") or "").lower()

        # Bypass raqamlar — har muhitda (prod ham) OTP yubormaydi, "0000" qabul qiladi.
        bypass_phones = getattr(settings, "BYPASS_PHONE_NUMBERS", [])
        if phone in bypass_phones:
            OTPCode.generate(phone=phone, purpose="login")
            return Response(
                {
                    "phone": phone,
                    "via": "bypass",
                    "message": f"{BYPASS_OTP_CODE} kod bilan kiring.",
                }
            )

        # Test foydalanuvchilar — botsiz, DEFAULT_OTP_CODE bilan. Prod'da
        # bypass yopilgan (faqat DEBUG yoki test runner muhitida ishlaydi).
        if phone.startswith("99800") and (
            settings.DEBUG or getattr(settings, "TESTING", False)
        ):
            OTPCode.generate(phone=phone, purpose="login")
            return Response(
                {
                    "phone": phone,
                    "via": "test",
                    "is_test_user": True,
                    "message": "Test foydalanuvchi — DEFAULT_OTP_CODE bilan kiring.",
                }
            )

        # Per-phone OTP resend chastota cheklovi — SMS/Telegram delivery
        # xarajati va spam himoyasi. Bot deeplink yo'li OTP yubormaydi
        # (kontakt verify'dan keyin bot generatsiya qiladi) — uni cheklamiz.
        if channel != "bot":
            ok, retry_after, reason = OTPCode.check_send_cooldown(phone)
            if not ok:
                msg = (
                    "Tez-tez urinish. Iltimos, biroz kuting."
                    if reason == "cooldown"
                    else "Bugungi limit oshib ketdi. Ertaga urinib ko'ring."
                )
                return Response(
                    {"detail": msg, "retry_after": retry_after},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": str(retry_after)},
                )

        user = User.objects.filter(phone=phone, is_active=True).first()

        # =================== LOGIN (mavjud user) ===================
        if user:
            # Telegram bog'langan + frontend SMS so'ramagan → Telegram'ga yuboramiz
            if user.telegram_chat_id and channel != "sms":
                otp = OTPCode.generate(
                    phone=phone,
                    purpose="login",
                    telegram_chat_id=user.telegram_chat_id,
                )
                if send_otp_via_telegram(user.telegram_chat_id, otp.code):
                    OTPCode.mark_sent(phone)
                    return Response(
                        {
                            "phone": phone,
                            "via": "telegram",
                            "message": "Tasdiqlash kodi Telegram orqali yuborildi.",
                        }
                    )
                # Telegram delivery failed → SMS fallback (otp qayta ishlatamiz)
                return _send_sms_otp_response(
                    phone, otp, "Telegram'da xato. Kod SMS orqali yuborildi."
                )

            # Telegram bog'lanmagan + frontend BOT tanlagan → bot deeplink.
            # Bot ichida kontakt verify qilingach, Telegram chat_id user'ga
            # bog'lanadi va keyingi loginlarda darrov Telegram orqali OTP keladi.
            if channel == "bot":
                return Response(
                    {
                        "phone": phone,
                        "via": "bot",
                        "deeplink": get_auth_deeplink(phone, role),
                        "message": (
                            "Telegram bog'lanmagan. Botga o'tib kontaktni "
                            "ulashing, kod chatga keladi."
                        ),
                    }
                )

            # Default — SMS (Telegram'siz user yoki frontend channel bermagan)
            otp = OTPCode.generate(phone=phone, purpose="login")
            return _send_sms_otp_response(
                phone, otp, "Tasdiqlash kodi SMS orqali yuborildi."
            )

        # =================== REGISTER (yangi user) ===================
        # SMS register — faqat OTP yuboriladi. Foydalanuvchi datalari (full_name,
        # referral) /auth/auth/verify/'da yuboriladi (OTP tasdiqlangach).
        if channel == "sms":
            otp = OTPCode.generate(phone=phone, purpose="register", role=role)
            return _send_sms_otp_response(
                phone, otp, "Tasdiqlash kodi SMS orqali yuborildi."
            )

        # Default: bot deeplink — ism + kontakt + referral bot ichida hal qilinadi
        return Response(
            {
                "phone": phone,
                "via": "bot",
                "deeplink": get_auth_deeplink(phone, role),
                "message": "Telegram botga o'ting va ko'rsatmalarni bajaring.",
            }
        )

    @extend_schema(
        request=AuthVerifySerializer,
        summary="Auth — OTP tasdiqlash",
        description=(
            "Backend OTP'ni tekshiradi va flow'ni aniqlaydi:\n\n"
            "- **Mavjud user**: JWT qaytariladi (login). Response: "
            "`{is_new: false, user, tokens}`.\n"
            "- **Yangi user, OTP'da `full_name` bor (bot register)**: user "
            "darhol yaratiladi. Response: `{is_new: true, user, tokens}`.\n"
            "- **Yangi user, OTP'da `full_name` yo'q (SMS register)**: "
            "vaqtinchalik `registration_token` qaytariladi (10 daqiqa). "
            "Frontend `/auth/complete-registration/`'ga full_name + role "
            "(+ doctor uchun referral_code) bilan murojaat qiladi."
        ),
    )
    @action(detail=False, methods=["post"], url_path="auth/verify")
    def auth_verify(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone"]
        code = serializer.validated_data["code"]
        requested_role = serializer.validated_data.get("active_role")
        context = serializer.validated_data.get("context")

        otp = OTPCode.verify_any(phone=phone, code=code)
        if otp is None:
            return Response(
                {"detail": "Kod noto'g'ri yoki muddati o'tgan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(phone=phone).first()
        is_new = user is None

        # Deaktivatsiya qilingan (admin bloklagan) user JWT ololmaydi — OTP
        # tekshiruvi o'tgan bo'lsa ham. SMS yo'lida user is_active=True filtri
        # bor, lekin bot/bypass/test kanallari OTP'ni is_active'siz generatsiya
        # qiladi — bu tekshiruv barcha kanallar uchun yagona himoya.
        if user is not None and not user.is_active:
            return Response(
                {"detail": "Akkaunt bloklangan. Iltimos, qo'llab-quvvatlashga murojaat qiling."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if is_new and not otp.full_name:
            # SMS register — OTP'da datalar yo'q. Phone tasdiqlangani uchun
            # vaqtinchalik signed token chiqaramiz; frontend
            # /auth/complete-registration/'ga full_name + role bilan murojaat qiladi.
            # Token'ga nonce qo'shib bir martalik consume qilamiz — replay attack
            # himoyasi (cache.add() atomic check complete-registration ichida).
            registration_token = signing.dumps(
                {
                    "phone": phone,
                    "role_hint": otp.role or "patient",
                    "telegram_chat_id": otp.telegram_chat_id,
                    "nonce": uuid.uuid4().hex,
                },
                salt=_REGISTRATION_TOKEN_SALT,
            )
            return Response(
                {
                    "is_new": True,
                    "registration_required": True,
                    "registration_token": registration_token,
                    "expires_in": _REGISTRATION_TOKEN_TTL_SEC,
                    "phone": phone,
                    "role_hint": otp.role or "patient",
                    "message": (
                        "Telefoningiz tasdiqlandi. Ro'yxatdan o'tishni yakunlash "
                        "uchun ma'lumotlaringizni yuboring."
                    ),
                },
                status=status.HTTP_200_OK,
            )

        if is_new:
            # Bot register — OTP'da full_name/role/referral_code/sex allaqachon
            # bor (bot validate qilgan). Darrov user yaratamiz.
            ref_code = (otp.referral_code or "").strip().upper()
            referred_by = (
                User.objects.filter(referral_code=ref_code).first()
                if ref_code
                else None
            )
            # telegram_chat_id'ni create'da emas, _link_telegram_chat orqali
            # bog'laymiz — unique konflikt (boshqa user'da shu chat_id) bo'lsa
            # IntegrityError → 500 o'rniga eski egasidan ajratiladi.
            user = User.objects.create_user(
                phone=phone,
                full_name=otp.full_name,
                role=otp.role or "patient",
                sex=otp.sex or None,
                referred_by=referred_by,
            )
            _link_telegram_chat(user, otp.telegram_chat_id)
            tokens = create_tokens_for_user(
                user,
                active_role=requested_role or user.role,
                context=context or "mobile",
            )
            response_status = status.HTTP_201_CREATED
        else:
            # Mavjud user — login. Bot qayta tasdiqlangan bo'lsa telegram_chat_id
            # yangilashimiz mumkin (foydalanuvchi yangi Telegram'ga o'tgan bo'lsa).
            _link_telegram_chat(user, otp.telegram_chat_id)
            try:
                tokens = create_tokens_for_user(
                    user, active_role=requested_role, context=context
                )
            except ValueError as e:
                return Response(
                    {"detail": str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            response_status = status.HTTP_200_OK

        return Response(
            {"is_new": is_new, **_user_payload(user, tokens)},
            status=response_status,
        )

    @extend_schema(
        request=CompleteRegistrationSerializer,
        summary="Auth — SMS register'ni yakunlash",
        description=(
            "SMS orqali ro'yxatdan o'tishning ikkinchi bosqichi. "
            "`/auth/auth/verify/`'dan olingan `registration_token` (10 daqiqa "
            "amal qiladi) bilan birga `full_name` va kerak bo'lsa "
            "`referral_code` (doctor uchun majburiy) yuboriladi.\n\n"
            "Token tasdiqlangan phone raqamini ichiga oladi — foydalanuvchi "
            "uni qayta o'zgartira olmaydi (signed/HMAC)."
        ),
    )
    @action(detail=False, methods=["post"], url_path="complete-registration")
    def complete_registration(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["registration_token"]
        full_name = serializer.validated_data["full_name"]
        role = serializer.validated_data.get("role") or "patient"
        sex = serializer.validated_data.get("sex") or None
        ref_code = (
            serializer.validated_data.get("referral_code") or ""
        ).strip().upper()
        requested_role = serializer.validated_data.get("active_role")
        context = serializer.validated_data.get("context")

        # Tokenni unsign qilish — phone token ichidan olinadi (foydalanuvchi
        # qayta o'zgartira olmaydi), TTL 10 daqiqa.
        try:
            payload = signing.loads(
                token,
                salt=_REGISTRATION_TOKEN_SALT,
                max_age=_REGISTRATION_TOKEN_TTL_SEC,
            )
        except signing.SignatureExpired:
            return Response(
                {
                    "detail": (
                        "Ro'yxatdan o'tish tokeni eskirgan. "
                        "Iltimos, telefoningizni qaytadan tasdiqlang."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            return Response(
                {"detail": "Token noto'g'ri."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        phone = payload.get("phone")
        telegram_chat_id = payload.get("telegram_chat_id")
        nonce = payload.get("nonce")
        if not phone:
            return Response(
                {"detail": "Token noto'g'ri."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Token one-time use — nonce allaqachon ishlatilgan bo'lsa rad etamiz.
        # Phone unique constraint'i ham bor (pastda), lekin u race oynani
        # to'liq yopa olmaydi (concurrent create attempt).
        if nonce:
            consumed = not cache.add(
                f"reg_token:nonce:{nonce}",
                1,
                timeout=_REGISTRATION_TOKEN_TTL_SEC + 60,
            )
            if consumed:
                return Response(
                    {"detail": "Bu token allaqachon ishlatilgan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Idempotency — token tasdiqlangach kim bo'lsa ham user yaratilgan
        # bo'lishi mumkin (parallel so'rov yoki qaytarib yuborish).
        if User.objects.filter(phone=phone).exists():
            return Response(
                {
                    "detail": (
                        "Bu telefon allaqachon ro'yxatdan o'tgan. "
                        "Iltimos, login qiling."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Referral code endi ixtiyoriy (doctor uchun ham). Agar berilgan bo'lsa,
        # mavjudligini tekshiramiz (admin yoki doctor referral code'i).
        if ref_code and not _is_valid_doctor_referral(ref_code):
            return Response(
                {"referral_code": ["Referral code topilmadi."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        referred_by = (
            User.objects.filter(referral_code=ref_code).first()
            if ref_code
            else None
        )

        user = User.objects.create_user(
            phone=phone,
            full_name=full_name,
            role=role,
            sex=sex,
            referred_by=referred_by,
        )
        # telegram_chat_id'ni alohida bog'laymiz — unique konflikt himoyasi.
        _link_telegram_chat(user, telegram_chat_id)

        tokens = create_tokens_for_user(
            user,
            active_role=requested_role or user.role,
            context=context or "mobile",
        )

        return Response(
            {"is_new": True, **_user_payload(user, tokens)},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={
            "200": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "full_name": {"type": "string"},
                    "role": {"type": "string"},
                    "avatar": {"type": "string", "nullable": True},
                },
            }
        },
        summary="Referral code bo'yicha user ma'lumoti",
        description="Doctor yoki Seller referral code orqali ma'lumot olish. App link / QR uchun.",
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="referral/(?P<code>[A-Za-z0-9]+)",
        throttle_classes=[ScopedRateThrottle],
    )
    def referral(self, request, code=None):
        # `referral_lookup` scope (10/min) bruteforce enumeration himoyasi.
        # `throttle_scope` ScopedRateThrottle uchun action attribute.
        self.throttle_scope = "referral_lookup"

        user = User.objects.filter(referral_code=code).first()
        if not user:
            security_logger.info(
                "referral_lookup_miss",
                extra={"code": code, "ip": request.META.get("REMOTE_ADDR")},
            )
            return Response(
                {"detail": "Referral code topilmadi."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "id": user.id,
                "full_name": user.full_name,
                "role": user.role,
                "avatar": generate_download_url(user.avatar) if user.avatar else None,
                "referral_code": user.referral_code,
            }
        )

    @extend_schema(
        request=LogoutSerializer,
        summary="Logout — tokenni bekor qilish",
        description="Refresh token yuboriladi, blacklist ga qo'shiladi. Access token muddati tugaguncha ishlaydi, lekin refresh bilan yangilab bo'lmaydi.",
    )
    @action(detail=False, methods=["post"], url_path="logout")
    def logout(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response(
                {"detail": "Token noto'g'ri yoki allaqachon bekor qilingan."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Logout qilingan device'ga keyingi push'lar bormaydi — eski/o'lik
        # tokenlar yig'ilib qolmasligi uchun.
        device_token = serializer.validated_data.get("device_token", "").strip()
        if device_token and request.user.is_authenticated:
            DeviceToken.objects.filter(
                user=request.user, token=device_token
            ).update(is_active=False)

        return Response({"detail": "Muvaffaqiyatli chiqildi."})

    @extend_schema(
        request=AccountDeletionRequestSerializer,
        summary="Akkauntni o'chirish so'rovi (autentifikatsiyasiz)",
        description=(
            "mediik.uz/delete form orqali yuboriladi. User login qila "
            "olmaydigan holatda ham akkaunti o'chirishi mumkin (Google Play talabi). "
            "Admin Telegram orqali xabar oladi va 30 kun ichida qo'lda ko'rib chiqadi."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="request-account-deletion",
        permission_classes=[AllowAny],
    )
    def request_account_deletion(self, request):
        serializer = AccountDeletionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data["phone"]
        email = serializer.validated_data.get("email") or ""
        reason = serializer.validated_data.get("reason") or ""

        # Rate limit: bir telefon raqamdan 24h ichida 1 ta so'rov yetarli.
        # Aks holda hujumchi/bot mingdan ortiq so'rov yuborib admin Telegram'ni
        # spam qiladi. Mavjud pending so'rov bo'lsa, yangisi yaratilmaydi va
        # silent OK qaytaramiz (rate-limit info'ni leak qilmaymiz).
        recent_cutoff = timezone.now() - timedelta(hours=24)
        existing = AccountDeletionRequest.objects.filter(
            phone=phone,
            requested_at__gte=recent_cutoff,
        ).order_by("-requested_at").first()
        if existing:
            logger.info(
                "Account deletion duplicate suppressed: phone=%s existing_id=%s",
                mask_phone(phone), existing.id,
            )
            return Response(
                {
                    "detail": (
                        "So'rov qabul qilindi. Admin 30 kun ichida ko'rib chiqadi."
                    ),
                    "request_id": existing.id,
                },
                status=status.HTTP_200_OK,
            )

        req = AccountDeletionRequest.objects.create(
            phone=phone,
            email=email or None,
            reason=reason,
        )

        logger.info(
            "Account deletion request #%s from phone=%s email=%s",
            req.id, mask_phone(phone), mask_email(email),
        )

        # Telegram orqali admin + qo'shimcha kuzatuvchilarga xabar (best-effort)
        try:
            import html

            user = User.objects.filter(phone=phone).first()
            # Akkaunt topilsa ismi ham qo'shiladi (xabar admin/kuzatuvchiga boradi).
            user_info = user.full_name or "mavjud (ismsiz)" if user else "topilmadi"

            text = (
                "🗑 <b>Akkaunt o'chirish so'rovi</b>\n\n"
                f"<b>Ism:</b> {html.escape(user_info)}\n"
                f"<b>Telefon:</b> {html.escape(phone)}\n"
                f"<b>Email:</b> {html.escape(email or '—')}\n"
                f"<b>Sabab:</b> {html.escape(reason or '—')}\n\n"
                f"<b>Request ID:</b> #{req.id}\n"
                f"Admin panel'dan ko'rib chiqing."
            )

            send_account_deletion_notice(text)
        except Exception as e:
            logger.warning("Telegram notification xatolik: %s", e)

        return Response(
            {
                "detail": (
                    "So'rovingiz qabul qilindi. Akkauntingiz 30 kun ichida o'chiriladi. "
                    "Agar fikringiz o'zgarsa, t.me/mediik_support orqali aloqaga chiqing."
                ),
                "request_id": req.id,
            },
            status=status.HTTP_201_CREATED,
        )
