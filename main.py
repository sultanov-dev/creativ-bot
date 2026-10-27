import asyncio
import logging
import os
import signal

from aiogram import Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import ADMIN_IDS, WEB_HOST, WEB_PORT, WEBHOOK_PATH, WEBHOOK_SECRET, WEBHOOK_URL
from database import close_db, get_known_group_ids, init_db
from handlers import get_routers
from utils.ai import close_session as close_ai_session
from utils.autodelete import AutoDeleteMiddleware, restore_pending_deletes
from utils.commands import setup_group_commands, setup_private_commands
from utils.create_bot import bot
from utils.expiry import run_expiry_loop
from utils.fsm_storage import SQLiteStorage
from utils.logging_setup import setup_logging
from utils.members import TrackMembersMiddleware
from utils.request_log import RequestLogMiddleware, UpdateLogMiddleware

logger = logging.getLogger(__name__)


def build_web_app(dp: Dispatcher) -> web.Application:
    """Webhook rejimi uchun aiohttp ilovasi: /webhook (maxfiy token bilan) va /health."""
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(
        app, path=WEBHOOK_PATH
    )
    setup_application(app, dp, bot=bot)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/health", health)
    return app


async def run_webhook(dp: Dispatcher) -> None:
    runner = web.AppRunner(build_web_app(dp))
    await runner.setup()
    await web.TCPSite(runner, WEB_HOST, WEB_PORT).start()
    await bot.set_webhook(
        url=f"{WEBHOOK_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=dp.resolve_used_update_types(),
    )
    logger.info("Webhook rejimi: %s%s (tinglanmoqda %s:%s)", WEBHOOK_URL, WEBHOOK_PATH, WEB_HOST, WEB_PORT)

    # Docker/systemd to'xtatganda (SIGTERM) tartibli yopilish
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()


async def main():
    # bot.db va loglar (shaxsiy ma'lumot) faqat egasi o'qiy oladigan ruxsat bilan yaratilsin
    os.umask(0o077)
    setup_logging()
    bot.session.middleware(RequestLogMiddleware())
    bot.session.middleware(AutoDeleteMiddleware())
    if not ADMIN_IDS:
        logger.error("ADMIN_IDS bo'sh: anketalarni ko'rib chiqadigan va buyruq beradigan admin yo'q (.env ni tekshiring)")

    dp = Dispatcher(storage=SQLiteStorage())
    dp.update.outer_middleware(UpdateLogMiddleware())
    dp.message.outer_middleware(TrackMembersMiddleware())
    dp.include_routers(*get_routers())

    await init_db()
    await setup_private_commands(bot)
    # yangi buyruqlar mavjud guruhlardagi admin menyusida ham chiqishi uchun
    # parallel: har bir chaqiruv ~0,4 s, ketma-ket qilinsa guruh/admin soniga ko'paya boradi
    await asyncio.gather(*(setup_group_commands(bot, g) for g in await get_known_group_ids()))
    await restore_pending_deletes(bot)
    expiry_task = asyncio.create_task(run_expiry_loop(bot))
    try:
        if WEBHOOK_URL:
            await run_webhook(dp)
        else:
            # polling o'zi eski webhook'ni o'chiradi
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        expiry_task.cancel()
        await close_ai_session()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
