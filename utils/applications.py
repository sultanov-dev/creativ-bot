from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import VOTING_MINUTES
from database import change_status, set_vote_message, start_voting
from keyboards.vote import vote_inline


async def open_voting(bot: Bot, app: dict) -> bool:
    """pending ariza uchun ovoz berishni boshlaydi: holat voting bo'ladi, guruhga ovoz xabari yuboriladi.

    Xabar yuborilmasa, holat pending'ga qaytariladi va False qaytadi.
    """
    if not await start_voting(app["id"], VOTING_MINUTES):
        return False

    try:
        vote_msg = await bot.send_message(
            chat_id=app["group_id"],
            text=(
                "🗳 <b>Yangi a'zo uchun ovoz berish</b>\n\n"
                f"{app['anketa']}\n\n"
                f"⏳ Ovoz berish <b>{VOTING_MINUTES}</b> daqiqa davom etadi. "
                "Muddat tugagach natija adminlarga yuboriladi, "
                "yakuniy qarorni esa adminlar qabul qiladi."
            ),
            reply_markup=vote_inline(app_id=app["id"]),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await change_status(app_id=app["id"], old="voting", new="pending")
        return False

    await set_vote_message(app_id=app["id"], message_id=vote_msg.message_id)
    return True
