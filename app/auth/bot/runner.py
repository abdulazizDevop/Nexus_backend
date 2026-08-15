from .common import *  # noqa: F401,F403 - header importlar + umumiy symbollar

async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(LogContextMiddleware())
    dp.include_router(router)

    print(f"🤖 Bot ishga tushdi — @{settings.TELEGRAM_BOT_USERNAME}")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    import os
    import sys
    import django

    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    asyncio.run(main())
