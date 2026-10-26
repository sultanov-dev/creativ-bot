import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from database import change_status, get_expired_applications
from utils.admin import safe_send

logger = logging.getLogger(__name__)

# ariza yaratilganidan boshlab shuncha kunda yakunlanmasa, muddati tugaydi (admin ko'rib chiqishi + ovoz berish)
EXPIRE_DAYS = 3
CHECK_INTERVAL = 600


async def expire_applications(bot: Bot) -> int:
    """Muddati o'tgan arizalarni yopadi: so'rov rad etiladi, ovoz xabari yopiladi, foydalanuvchiga xabar ketadi."""
    expired = 0
    for app in await get_expired_applications(EXPIRE_DAYS):
        # holat o'zgargan bo'lsa (masalan, ayni paytda ovoz yakunlangan), change_status False qaytaradi
        if not await change_status(app["id"], old=app["status"], new="expired"):
            continue
        expired += 1
        logger.info("Ariza %s muddati tugadi (oldingi holat: %s)", app["id"], app["status"])

        try:
            await bot.decline_chat_join_request(
                chat_id=app["group_id"], user_id=app["user_id"]
            )
        except TelegramAPIError:
            pass  # so'rov allaqachon hal qilingan yoki foydalanuvchi guruhda

        if app["vote_message_id"]:
            try:
                await bot.edit_message_text(
                    chat_id=app["group_id"],
                    message_id=app["vote_message_id"],
                    text=f"{app['anketa']}\n⌛ Ovoz berish muddati tugadi, ariza yopildi.",
                )
            except TelegramAPIError:
                pass

        await safe_send(
            bot=bot,
            chat_id=app["user_id"],
            text=(
                f"Arizangiz {EXPIRE_DAYS} kun ichida ko'rib chiqilmadi va yopildi. "
                "Xohlasangiz, guruhga qayta qo'shilish so'rovini yuborishingiz mumkin."
            ),
        )
    return expired


async def run_expiry_loop(bot: Bot) -> None:
    """Fon vazifasi: ishga tushganda va keyin har 10 daqiqada tekshiradi; xato bo'lsa ham to'xtamaydi."""
    while True:
        try:
            await expire_applications(bot)
        except Exception:
            logger.exception("Arizalar muddatini tekshirishda xatolik")
        await asyncio.sleep(CHECK_INTERVAL)
