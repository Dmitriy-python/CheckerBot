import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from database.database import init_db, add_sample_messages
from routers.admin_router import admin_router
from routers.bot_router import bot_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(bot_router)
dp.include_router(admin_router)


async def main():
    logger.info("🚀 Bot starting...")
    init_db()
    add_sample_messages()
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot stopped with error: {e}")
    finally:
        logger.info("🛑 Bot stopped")
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())



