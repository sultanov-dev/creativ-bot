import asyncio
import os

from aiogram import Dispatcher

from database import close_db, get_known_group_ids, init_db
from handlers import get_routers
from utils.commands import setup_group_commands, setup_private_commands
from utils.create_bot import bot
from utils.expiry import run_expiry_loop
from utils.fsm_storage import SQLiteStorage
from utils.logging_setup import setup_logging
from utils.members import TrackMembersMiddleware
from utils.request_log import RequestLogMiddleware, UpdateLogMiddleware


async def main():
    # bot.db va loglar (shaxsiy ma'lumot) faqat egasi o'qiy oladigan ruxsat bilan yaratilsin
    os.umask(0o077)
    setup_logging()
    bot.session.middleware(RequestLogMiddleware())

    dp = Dispatcher(storage=SQLiteStorage())
    dp.update.outer_middleware(UpdateLogMiddleware())
    dp.message.outer_middleware(TrackMembersMiddleware())
    dp.include_routers(*get_routers())

    await init_db()
    await setup_private_commands(bot)
    # yangi buyruqlar mavjud guruhlardagi creator menyusida ham chiqishi uchun
    for group_id in await get_known_group_ids():
        await setup_group_commands(bot, group_id)
    expiry_task = asyncio.create_task(run_expiry_loop(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        expiry_task.cancel()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
