import asyncio
import logging

from aiogram import Dispatcher

from database import DB_PATH, init_db
from handlers import get_routers
from utils.commands import setup_private_commands
from utils.create_bot import bot
from utils.fsm_storage import SQLiteStorage
from utils.members import TrackMembersMiddleware


async def main():
    logging.basicConfig(level=logging.INFO)
    dp = Dispatcher(storage=SQLiteStorage(DB_PATH))
    dp.message.outer_middleware(TrackMembersMiddleware())
    dp.include_routers(*get_routers())

    await init_db()
    await setup_private_commands(bot)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
