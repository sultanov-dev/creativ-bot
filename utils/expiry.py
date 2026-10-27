import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import DATA_RETENTION_DAYS
from database import change_status, get_expired_applications, purge_old_data
from utils.admin import safe_send
from utils.join_requests import settle_join_request
from utils.voting import finalize_due_votings

logger = logging.getLogger(__name__)

# admin shuncha kun ichida ko'rib chiqmasa, ariza muddati tugaydi (ovoz berish muddati alohida: VOTING_MINUTES)
EXPIRE_DAYS = 3
PURGE_INTERVAL = 3600  # eski ma'lumotlar tekshiruvi (soniya)
CHECK_INTERVAL = 15  # ovoz muddati tugagach xabar ko'pi bilan shuncha soniyadan keyin o'chadi


async def expire_applications(bot: Bot) -> int:
    """Admin ko'rib chiqmagan muddati o'tgan arizalarni yopadi: so'rov rad etiladi, ovoz xabari yopiladi, foydalanuvchiga xabar ketadi."""
    expired = 0
    for app in await get_expired_applications(EXPIRE_DAYS):
        # holat o'zgargan bo'lsa (masalan, ayni paytda ovoz yakunlangan), change_status False qaytaradi
        if not await change_status(app["id"], old=app["status"], new="expired"):
            continue
        expired += 1
        logger.info("Ariza %s muddati tugadi (oldingi holat: %s)", app["id"], app["status"])

        await settle_join_request(bot, app, False)

        if app["vote_message_id"]:
            try:
                await bot.edit_message_text(
                    chat_id=app["group_id"],
                    message_id=app["vote_message_id"],
                    text=f"{app['anketa']}\n⌛ Ariza {EXPIRE_DAYS} kun ichida ko'rib chiqilmadi va yopildi.",
                )
            except TelegramAPIError:
                pass

        await safe_send(
            bot=bot,
            chat_id=app["user_id"],
            text=(
                f"Kechirasiz, arizangiz {EXPIRE_DAYS} kun ichida ko'rib chiqilmadi va yopildi. "
                "Xohlasangiz, guruhga qo'shilish so'rovini qayta yuborishingiz mumkin."
            ),
        )
    return expired


async def run_expiry_loop(bot: Bot) -> None:
    """Fon vazifasi: ishga tushganda va keyin har daqiqada tekshiradi; xato bo'lsa ham to'xtamaydi."""
    last_purge = float("-inf")
    while True:
        try:
            await expire_applications(bot)
            await finalize_due_votings(bot)
            if time.monotonic() - last_purge >= PURGE_INTERVAL:
                last_purge = time.monotonic()
                removed = await purge_old_data(DATA_RETENTION_DAYS)
                if removed:
                    logger.info("Saqlash muddati tugagan %s ta ariza ma'lumoti o'chirildi", removed)
        except Exception:
            logger.exception("Arizalar muddatini tekshirishda xatolik")
        await asyncio.sleep(CHECK_INTERVAL)
