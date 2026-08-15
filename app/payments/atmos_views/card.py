from .common import *  # noqa: F401,F403 - header importlar + helperlar
from .common import _atmos_error_response  # underscore helper (star bermaydi)

@extend_schema(tags=["Payments - Atmos (Patient)"])
class AtmosCardViewSet(viewsets.ViewSet):
    """Atmos saqlangan kartalar — patient o'z kartalarini boshqaradi."""

    permission_classes = [IsPatient]
    queryset = AtmosSavedCard.objects.none()

    def get_serializer_class(self):
        if self.action == "bind":
            return AtmosCardBindSerializer
        if self.action == "confirm":
            return AtmosCardConfirmSerializer
        return AtmosSavedCardSerializer

    @extend_schema(
        summary="Saqlangan kartalar ro'yxati",
        responses=AtmosSavedCardSerializer(many=True),
    )
    def list(self, request):
        cards = AtmosSavedCard.objects.filter(user=request.user)
        return Response(AtmosSavedCardSerializer(cards, many=True).data)

    @extend_schema(
        summary="Karta qo'shish — 1-bosqich (SMS yuboriladi)",
        request=AtmosCardBindSerializer,
        responses={200: AtmosCardBindResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="bind")
    def bind(self, request):
        serializer = AtmosCardBindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        max_cards = settings.ATMOS["MAX_SAVED_CARDS"]
        if AtmosSavedCard.objects.filter(user=request.user).count() >= max_cards:
            return Response(
                {"detail": f"Maksimal {max_cards} ta karta saqlashingiz mumkin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        card_number = serializer.validated_data["card_number"]
        expiry = serializer.validated_data["expiry"]
        try:
            data = atmos_client.bind_card_init(
                card_number=card_number,
                expiry=expiry,
            )
        except AtmosError as exc:
            logger.warning("Atmos bind_card_init xatosi: user=%s err=%s", request.user.id, exc)
            return _atmos_error_response(exc)

        atmos_tx_id = data.get("transaction_id")
        # confirm() bosqichida pre-apply uchun kerak — Atmos javobi faqat masked
        # PAN qaytaradi, to'liq PAN'ni biz lokal saqlashimiz kerak.
        if atmos_tx_id:
            cache.set(
                f"atmos:bind:{atmos_tx_id}",
                {"card_number": card_number, "expiry": expiry},
                600,
            )

        logger.info(
            "Atmos bind init: user=%s atmos_tx=%s",
            request.user.id, atmos_tx_id,
        )
        return Response(
            {
                "atmos_tx_id": atmos_tx_id,
                "phone_masked": data.get("phone", ""),
            }
        )

    @extend_schema(
        summary="Karta qo'shish — 2-bosqich (OTP bilan tasdiqlash)",
        request=AtmosCardConfirmSerializer,
        responses={200: AtmosSavedCardSerializer},
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="confirm",
        throttle_classes=[OtpConfirmThrottle],
    )
    def confirm(self, request):
        serializer = AtmosCardConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = atmos_client.bind_card_confirm(
                transaction_id=serializer.validated_data["atmos_tx_id"],
                otp=serializer.validated_data["otp"],
            )
        except AtmosError as exc:
            logger.warning(
                "Atmos bind_card_confirm xatosi: user=%s err=%s",
                request.user.id, exc,
            )
            return _atmos_error_response(exc)

        card_data = data.get("data", {})
        atmos_card_id = card_data.get("card_id")
        card_token = card_data.get("card_token")
        if not atmos_card_id or not card_token:
            logger.error(
                "Atmos bind confirm: card_id/card_token yo'q user=%s data=%s",
                request.user.id, card_data,
            )
            return Response(
                {"detail": "Atmos javobida karta ma'lumotlari to'liq emas."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        atmos_tx_id = serializer.validated_data["atmos_tx_id"]
        bind_cache = cache.get(f"atmos:bind:{atmos_tx_id}") or {}
        full_card_number = bind_cache.get("card_number", "")

        with transaction.atomic():
            is_first = not AtmosSavedCard.objects.filter(user=request.user).exists()
            card, created = AtmosSavedCard.objects.update_or_create(
                atmos_card_id=atmos_card_id,
                defaults={
                    "user": request.user,
                    "card_token": card_token,
                    "card_number": full_card_number,
                    "pan_masked": card_data.get("pan", ""),
                    "expiry": card_data.get("expiry", ""),
                    "is_primary": is_first,
                },
            )

        cache.delete(f"atmos:bind:{atmos_tx_id}")

        logger.info(
            "Atmos karta saqlandi: user=%s card=%s atmos_card_id=%s created=%s",
            request.user.id, card.id, atmos_card_id, created,
        )
        return Response(AtmosSavedCardSerializer(card).data)

    @extend_schema(summary="Karta o'chirish")
    def destroy(self, request, pk=None):
        card = AtmosSavedCard.objects.filter(pk=pk, user=request.user).first()
        if not card:
            return Response(
                {"detail": "Karta topilmadi."}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            atmos_client.remove_card(card.atmos_card_id, card.card_token)
        except AtmosError as exc:
            # Atmos tomonda yo'q bo'lib qolgan bo'lishi mumkin — log qilamiz lekin
            # bizning DB'dan baribir o'chiramiz, aks holda foydalanuvchi qolib ketadi.
            logger.warning(
                "Atmos remove_card xatosi (lokal o'chirish davom etadi): user=%s card=%s err=%s",
                request.user.id, card.id, exc,
            )

        was_primary = card.is_primary
        card.delete()

        if was_primary:
            next_card = AtmosSavedCard.objects.filter(user=request.user).first()
            if next_card:
                next_card.make_primary()

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(summary="Kartani primary qilish")
    @action(detail=True, methods=["post"], url_path="make-primary")
    def make_primary(self, request, pk=None):
        card = AtmosSavedCard.objects.filter(pk=pk, user=request.user).first()
        if not card:
            return Response(
                {"detail": "Karta topilmadi."}, status=status.HTTP_404_NOT_FOUND
            )
        card.make_primary()
        return Response(AtmosSavedCardSerializer(card).data)


# ---------- To'lov ----------
