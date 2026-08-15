from .common import *  # noqa: F401,F403 - importlar + AVATAR_* + top-level helperlar
from .common import _soft_delete_user  # underscore helper (star bermaydi)


class SelfMixin:
    """Bemor o'zi (me/switch/delete/avatar) — UserViewSet mixin."""

    @extend_schema(
        request=UserUpdateSerializer,
        responses=UserSerializer,
        summary="O'z profili — ko'rish va yangilash",
        description="GET: profil + settings qaytaradi. PATCH: profil + settings birga yangilanadi.",
    )
    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request):
        user = request.user
        UserSettings.objects.get_or_create(user=user)

        if request.method == "PATCH":
            serializer = UserUpdateSerializer(
                user,
                data=request.data,
                partial=True,
                context={"request": request},  # validate_avatar user'ni shu orqali oladi
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        user.refresh_from_db()
        return Response(UserSerializer(user).data)

    @extend_schema(
        summary="Rolni almashtirish (switch)",
        description=(
            "Admin → admin/doctor/patient.\n"
            "Doctor → doctor/patient.\n"
            "Patient → faqat patient.\n"
            "Doctor rejimiga birinchi marta o'tsa DoctorProfile avtomatik yaratiladi."
        ),
    )
    @action(detail=False, methods=["patch"], url_path="me/switch-role")
    def switch_role(self, request):
        """active_role'ni o'zgartiradi va YANGI JWT token juftligini qaytaradi.

        Token ichida active_role saqlanadi — switch qilingach, eski token
        eski role bilan qoladi, yangi token yangi role bilan. Frontend yangi
        tokenni saqlab, keyingi so'rovlarda ishlatadi.
        """
        new_role = request.data.get("active_role", "").strip()
        user = request.user
        allowed = user.allowed_roles

        if new_role not in allowed:
            return Response(
                {
                    "detail": f"Sizga bu rolga o'tish ruxsati yo'q. Mumkin: {allowed}",
                    "allowed_roles": allowed,
                },
                status=400,
            )

        if new_role == User.Role.DOCTOR:
            DoctorProfile.objects.get_or_create(
                user=user, defaults={"is_verified": False}
            )

        # DB field ham yangilanadi (backward compat + audit)
        user.active_role = new_role
        user.save(update_fields=["active_role"])

        # Yangi token — active_role + scope + patient_id + doctor_id claim'lari
        tokens = create_tokens_for_user(user, active_role=new_role)

        return Response(
            {
                "active_role": new_role,
                "scope": tokens["scope"],
                "allowed_roles": allowed,
                "patient_id": tokens["patient_id"],
                "doctor_id": tokens["doctor_id"],
                "tokens": {
                    "access": tokens["access"],
                    "refresh": tokens["refresh"],
                },
                "message": (
                    f"Rejim o'zgartirildi: {new_role}. "
                    "Yangi tokenni saqlab, keyingi so'rovlarda ishlating."
                ),
            }
        )

    @extend_schema(
        request=DeleteMyAccountSerializer,
        responses={200: None, 204: None},
        summary="O'z akkauntini yoki profilini o'chirish (Apple/Google talabi)",
        description=(
            "`scope` bilan nimani o'chirishni belgilaydi:\n\n"
            "**scope=all** (default) — butun akkaunt (legacy). PII "
            "anonimlashtiriladi, is_active=False, tokenlar blacklist. Moliyaviy "
            "yozuvlar (Payment/ProSubscription/DoctorBalance) audit uchun saqlanadi.\n\n"
            "**scope=doctor** — FAQAT doctor profili o'chadi. Operatsion doctor "
            "datasi (jadval, sertifikat, tarif, karta, AI, bemor bog'lanishlari) "
            "to'liq o'chadi; moliyaviy/audit (balans, sotuv, payout, review, "
            "yakunlangan uchrashuv) ANONIM saqlanadi (admin statistikasi tushmaydi). "
            "User bemor sifatida ishlashda davom etadi.\n\n"
            "**scope=patient** — FAQAT bemor datasi o'chadi (muolaja, sog'liq "
            "ko'rsatkichlari, tibbiy karta, diet). Doctor profili bo'lsa User "
            "doctor sifatida qoladi; bo'lmasa butun akkaunt o'chadi (=all).\n\n"
            "Cheklov: root admin o'z akkauntini o'chira olmaydi."
        ),
    )
    @action(detail=False, methods=["delete"], url_path="me/delete-account")
    def delete_my_account(self, request):
        from app.users.deletion import delete_doctor_profile, delete_patient_data

        user = request.user

        if user.is_root_admin:
            return Response(
                {"detail": "Root admin o'z akkauntini o'chira olmaydi."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DeleteMyAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scope = serializer.validated_data.get("scope", "all")
        reason = serializer.validated_data.get("reason", "")
        refresh = serializer.validated_data.get("refresh", "")

        if scope == "doctor":
            ok = delete_doctor_profile(user)
            if not ok:
                return Response(
                    {"detail": "Sizda doctor profili yo'q yoki allaqachon o'chirilgan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": "Doctor profili o'chirildi.", "scope": "doctor"},
                status=status.HTTP_200_OK,
            )

        if scope == "patient":
            result = delete_patient_data(user, reason=reason, refresh_token=refresh)
            if result == "account":
                # Doctor profili yo'q edi → butun akkaunt o'chdi (tokenlar bekor)
                return Response(status=status.HTTP_204_NO_CONTENT)
            return Response(
                {"detail": "Bemor ma'lumotlari o'chirildi.", "scope": "patient_only"},
                status=status.HTTP_200_OK,
            )

        # scope == "all" — legacy: butun akkaunt soft-delete
        _soft_delete_user(user, reason=reason, refresh_token=refresh)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Avatar yuklash uchun presigned URL olish",
        description="file_name, file_type va file_size yuboriladi. Maksimal 5MB. Qaytgan upload_url ga PUT qilib rasm yuklanadi.",
    )
    @action(detail=False, methods=["post"], url_path="me/avatar-upload-url")
    def avatar_upload_url(self, request):
        file_name = request.data.get("file_name", "avatar.jpg")
        file_type = request.data.get("file_type", "image/jpeg")
        file_size = request.data.get("file_size")

        # Maksimal AVATAR_MAX_BYTES — S3 cost va abuse'dan himoyalaydi.
        # Production'da S3 bucket policy bilan qo'shimcha chegara qo'yilishi
        # tavsiya etiladi (presigned URL'da file_size cheklovi yo'q).
        try:
            file_size_int = int(file_size) if file_size is not None else None
        except (TypeError, ValueError):
            return Response({"detail": "file_size noto'g'ri."}, status=400)
        if file_size_int is not None and file_size_int > AVATAR_MAX_BYTES:
            return Response(
                {"detail": "Avatar 5MB dan oshmasligi kerak."}, status=400
            )

        if file_type not in AVATAR_ALLOWED_TYPES:
            return Response(
                {"detail": f"Faqat {', '.join(AVATAR_ALLOWED_TYPES)} ruxsat etilgan"},
                status=400,
            )

        file_key = generate_avatar_key(request.user.id, file_name)
        upload_url = generate_upload_url(file_key, file_type)

        return Response(
            {
                "upload_url": upload_url,
                "file_key": file_key,
                "expires_in": 900,
            }
        )
