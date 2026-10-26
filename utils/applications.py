import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReplyKeyboardRemove

from config import VOTING_MINUTES
from database import (
    change_status,
    create_application,
    get_application,
    set_vote_message,
    start_voting,
)
from keyboards.vote import vote_inline
from texts import ALREADY_APPLIED, ERROR_GENERIC, REPEAT_APPLICATION_SENT
from utils.admin import safe_send
from utils.form_anketa import format_anketa, full_name_of

logger = logging.getLogger(__name__)


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
                f"{app['anketa']}"
            ),
            reply_markup=vote_inline(app_id=app["id"]),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await change_status(app_id=app["id"], old="voting", new="pending")
        return False

    await set_vote_message(app_id=app["id"], message_id=vote_msg.message_id)
    return True


async def apply_from_profile(
    bot: Bot, user_id: int, group_id: int, chat_id: int, profile: dict
) -> None:
    """Saqlangan (yoki tahrirlangan) anketa bilan to'g'ridan-to'g'ri guruh ovoziga qo'yadi."""
    app_id = await create_application(
        user_id,
        group_id,
        full_name_of(profile),
        format_anketa(profile),
        first_name=profile.get("first_name"),
        last_name=profile.get("last_name"),
        tg_username=profile.get("username"),
        phone=profile.get("phone"),
    )
    if app_id is None:
        await safe_send(bot=bot, chat_id=chat_id, text=ALREADY_APPLIED, reply_markup=ReplyKeyboardRemove())
        return

    app = await get_application(app_id)
    if app is None or not await open_voting(bot, app):
        # ovoz xabari guruhga ketmadi: ariza osilib qolmasin, foydalanuvchi qayta urinishi mumkin
        logger.warning("Saqlangan anketa bilan ovoz berishni boshlab bo'lmadi, ariza %s", app_id)
        await change_status(app_id, old="pending", new="failed")
        await safe_send(bot=bot, chat_id=chat_id, text=ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    await safe_send(bot=bot, chat_id=chat_id, text=REPEAT_APPLICATION_SENT, reply_markup=ReplyKeyboardRemove())
