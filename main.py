import asyncio
import logging

from aiogram import Dispatcher

from database import init_db
from handlers import get_routers
from utils.create_bot import bot


async def main():
    logging.basicConfig(level=logging.INFO)
    dp = Dispatcher()
    dp.include_routers(*get_routers())

    await init_db()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
