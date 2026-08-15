import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Telegram botni polling rejimida ishga tushirish (aiogram)"

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stderr.write(self.style.ERROR(
                "TELEGRAM_BOT_TOKEN .env faylida topilmadi!"
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"🤖 Telegram bot ishga tushmoqda... (@{settings.TELEGRAM_BOT_USERNAME})"
        ))

        from app.auth.bot import main
        asyncio.run(main())
