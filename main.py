import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from config import settings
from database import async_session_factory, create_tables
from middlewares import DbSessionMiddleware

from user_handlers import router as user_router
from master_handlers import router as master_router
from admin_handlers import router as admin_router
from admin_extended_handlers import router as admin_extended_router # <-- Импортируем новый роутер


async def main():
    logging.basicConfig(level=logging.INFO)

    await create_tables()

    storage = MemoryStorage()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher(storage=storage)

    dp.update.middleware(DbSessionMiddleware(session_pool=async_session_factory))

    # Регистрируем роутеры. Важен порядок: сначала более специфичные (админские), потом общие.
    dp.include_router(admin_router)
    dp.include_router(admin_extended_router) # <-- Регистрируем новый роутер
    dp.include_router(master_router)
    dp.include_router(user_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")
