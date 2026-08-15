"""FCM push diagnostikasi — nega push qurilmaga kelmayotganini aniqlash.

Ishlatish (Docker):
    docker compose exec web python manage.py fcm_check                 # umumiy holat
    docker compose exec web python manage.py fcm_check 998880493393    # raqam tokenlari
    docker compose exec web python manage.py fcm_check 998880493393 --send   # jonli test push

`push_sent` (FCM `send()` muvaffaqiyatli) qurilmaga YETKAZILDI degani EMAS — bu
command FCM qabul qilish-qilmasligini va aniq xatoni ko'rsatadi. Yetkazish
muammosi odatda: iOS → Firebase APNs key; Android → app permission/foreground.
"""

from collections import Counter

from django.core.management.base import BaseCommand

from app.notifications.models import DeviceToken


class Command(BaseCommand):
    help = "FCM push diagnostikasi (Firebase loyiha, tokenlar, jonli test send)."

    def add_arguments(self, parser):
        parser.add_argument("phone", nargs="?", help="Telefon (oxiri yetarli, masalan 998880493393)")
        parser.add_argument("--send", action="store_true", help="Jonli test push yuborish")
        parser.add_argument(
            "--platform", choices=["ios", "android", "web"],
            help="Test uchun shu platform token'i (masalan iOS'ni tekshirish)",
        )
        parser.add_argument(
            "--scope", choices=["patient", "doctor", "admin"],
            help="Test uchun shu app_scope token'i (bir qurilmada doctor+patient app alohida)",
        )
        parser.add_argument("--token-id", type=int, help="Aniq token id'ni test qilish")

    def handle(self, *args, **opts):
        from services.firebase import _build_message, _get_app

        app = _get_app()
        project = getattr(app, "project_id", None)
        self.stdout.write(f"=== Firebase loyiha: {project or 'INITIALIZE BOLMAGAN (creds yo`q?)'} ===")

        qs = DeviceToken.objects.filter(is_active=True, token_type=DeviceToken.TokenType.FCM)
        self.stdout.write(f"Aktiv FCM tokenlar: {qs.count()}")
        self.stdout.write(f"  platform : {dict(Counter(qs.values_list('platform', flat=True)))}")
        self.stdout.write(f"  app_scope: {dict(Counter(qs.values_list('app_scope', flat=True)))}")

        phone = opts.get("phone")
        if not phone:
            self.stdout.write("\nRaqam tokenlari + test uchun: fcm_check 998... --send")
            return

        mine = list(
            DeviceToken.objects.filter(
                user__phone__endswith=phone,
                is_active=True,
                token_type=DeviceToken.TokenType.FCM,
            ).select_related("user")
        )
        self.stdout.write(f"\n{phone} ning aktiv FCM tokenlari ({len(mine)}):")
        for t in mine:
            self.stdout.write(
                f"  id={t.id} platform={t.platform} scope={t.app_scope} "
                f"last_used={t.last_used_at} tok={t.token[:20]}..."
            )

        if not mine:
            self.stdout.write(
                self.style.WARNING(
                    "\nBu raqamda aktiv FCM token YO'Q — app token register qilmagan "
                    "(yoki boshqa env/Firebase loyihaga). Push borishi mumkin emas."
                )
            )
            return

        if not opts.get("send"):
            self.stdout.write("\nJonli test uchun: --send (+ ixtiyoriy --platform ios / --token-id N).")
            return

        # Qaysi token'ni test qilamiz: token-id > (platform+scope filtr) > birinchisi
        if opts.get("token_id"):
            target = next((t for t in mine if t.id == opts["token_id"]), None)
        else:
            candidates = mine
            if opts.get("platform"):
                candidates = [t for t in candidates if t.platform == opts["platform"]]
            if opts.get("scope"):
                candidates = [t for t in candidates if t.app_scope == opts["scope"]]
            target = candidates[0] if candidates else None
        if not target:
            self.stdout.write(self.style.ERROR("Mos token topilmadi (--platform/--scope/--token-id tekshiring)."))
            return

        from firebase_admin import messaging

        self.stdout.write(f"\nTest push → token id={target.id} ({target.platform}, {target.app_scope})...")
        msg = _build_message(target.token, "Test push", "fcm_check diagnostika", {"type": "test"}, False, False)
        try:
            mid = messaging.send(msg)
            self.stdout.write(self.style.SUCCESS(f"FCM QABUL QILDI ✅  message_id: {mid}"))
            self.stdout.write(
                "  → FCM yetkazishni o'z zimmasiga oldi. Qurilmaga KELMASA:\n"
                "    iOS     = Firebase Console'da APNs Auth Key (.p8) yo'q/noto'g'ri (prod bundle).\n"
                "    Android = app foreground (banner avtomatik chiqmaydi) yoki notification permission yo'q."
            )
        except Exception as e:  # noqa: BLE001 — diagnostika, aniq xatoni ko'rsatamiz
            self.stdout.write(self.style.ERROR(f"FCM XATO ❌  {type(e).__name__}: {e}"))
            self.stdout.write(
                "  'SenderId mismatch' → token boshqa Firebase loyihaniki (app↔backend mos emas).\n"
                "  'Requested entity not found' / 'registration-token-not-registered' → token eskirgan."
            )
