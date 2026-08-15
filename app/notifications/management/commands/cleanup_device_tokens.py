"""DeviceToken churn tozalash.

iOS reinstall'da identifierForVendor (device_id) o'zgaradi → har qayta o'rnatish
yangi token qatori yaratadi va eskisi `is_active=True` qolib ketadi. Vaqt o'tib
bitta userda o'nlab "aktiv" token to'planadi — silent push'larni sekinlashtiradi
va iOS background push throttle'ni og'irlashtiradi.

Bu buyruq har (user, app_scope, token_type) bo'yicha eng so'nggi `--keep` tokenni
qoldirib, qolganini o'chiradi. Registration view endi buni avtomatik qiladi
(MAX_TOKENS_PER_SCOPE) — bu buyruq mavjud to'planib qolganlarni bir marta tozalash
va keyinchalik davriy ishlatish uchun.

Misol:
    python manage.py cleanup_device_tokens --dry-run      # nima o'chishini ko'rsatadi
    python manage.py cleanup_device_tokens --keep 3        # eng so'nggi 3 tani qoldiradi
    python manage.py cleanup_device_tokens --stale-days 60 # 60 kun ishlatilmaganlarni ham
"""

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

from app.notifications.models import DeviceToken


class Command(BaseCommand):
    help = "DeviceToken churn'ni tozalaydi (har user+scope+type bo'yicha eng so'nggi N tokenni qoldiradi)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep", type=int, default=3,
            help="Har (user, app_scope, token_type) bo'yicha qoldiriladigan token soni (default 3).",
        )
        parser.add_argument(
            "--stale-days", type=int, default=0,
            help="Berilsa, last_used_at shu kundan eski tokenlar ham o'chadi (default 0 = o'chiq).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Hech narsa o'chirmaydi — faqat nima o'chishini chiqaradi.",
        )

    def handle(self, *args, **opts):
        keep = opts["keep"]
        stale_days = opts["stale_days"]
        dry = opts["dry_run"]
        prefix = "(dry-run) " if dry else ""

        delete_ids: set[int] = set()

        # 1) Har guruh bo'yicha eng so'nggi `keep` tokendan eskisi
        groups = (
            DeviceToken.objects.values("user_id", "app_scope", "token_type")
            .annotate(c=Count("id"))
            .filter(c__gt=keep)
        )
        for g in groups:
            extra = (
                DeviceToken.objects.filter(
                    user_id=g["user_id"],
                    app_scope=g["app_scope"],
                    token_type=g["token_type"],
                )
                .order_by("-last_used_at")
                .values_list("id", flat=True)[keep:]
            )
            delete_ids.update(extra)

        # 2) (Ixtiyoriy) uzoq ishlatilmagan tokenlar
        if stale_days > 0:
            cutoff = timezone.now() - timedelta(days=stale_days)
            stale = DeviceToken.objects.filter(
                last_used_at__lt=cutoff
            ).values_list("id", flat=True)
            delete_ids.update(stale)

        total = DeviceToken.objects.count()
        self.stdout.write(
            f"{prefix}Jami token: {total} | o'chiriladi: {len(delete_ids)} | "
            f"qoladi: {total - len(delete_ids)}"
        )

        if delete_ids and not dry:
            DeviceToken.objects.filter(id__in=delete_ids).delete()
            self.stdout.write(self.style.SUCCESS(f"{len(delete_ids)} ta token o'chirildi."))
        elif dry:
            self.stdout.write("Hech narsa o'chirilmadi (--dry-run).")
