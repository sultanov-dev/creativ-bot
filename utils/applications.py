import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ReplyKeyboardRemove

from config import VOTING_MINUTES
from database import (
    change_status,
    create_application,
    get_application,
    get_undelivered_applications,
    mark_admins_notified,
    set_vote_message,
    start_voting,
)
from aiogram.fsm.storage.base import BaseStorage

from keyboards.action import action_inline
from keyboards.vote import vote_inline
from states import Form
from texts import ALREADY_APPLIED, ERROR_GENERIC, REPEAT_APPLICATION_SENT, THANKS, VOTE_DEADLINE
from utils.admin import reviewer_ids, safe_send
from utils.form_anketa import anketa_for_admins, format_anketa, full_name_of
from utils.fsm import get_private_state
from utils.timefmt import format_deadline

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
                "🗳 <b>Yangi a'zo uchun ovoz berish</b>\n"
                f"{VOTE_DEADLINE.format(when=format_deadline(VOTING_MINUTES))}\n\n"
                f"{app['anketa']}"
            ),
            reply_markup=vote_inline(app_id=app["id"]),
        )
    except TelegramAPIError:
        await change_status(app_id=app["id"], old="voting", new="pending")
        return False

    try:
        await set_vote_message(app_id=app["id"], message_id=vote_msg.message_id)
    except Exception:
        # id yozilmasa xabar yetim qolardi: o'chiramiz va ariza qayta ko'rib chiqilishi uchun pending'ga qaytaramiz
        logger.exception("Ariza %s: ovoz xabari id'sini yozib bo'lmadi", app["id"])
        try:
            await bot.delete_message(chat_id=app["group_id"], message_id=vote_msg.message_id)
        except TelegramAPIError:
            pass
        await change_status(app_id=app["id"], old="voting", new="pending")
        return False
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


async def redeliver_undelivered(bot: Bot, storage: BaseStorage) -> int:
    """Startda: to'liq anketasi bor (ariza yaratilgan), lekin adminlarga yetib bormagan arizalarni qayta yuboradi.

    Yarim qolgan anketalar (ariza yaratilmagan) bu yerga kirmaydi: ular adminlarga hech qachon bormaydi.
    Hech bir admin olmasa ariza `failed` bo'ladi. Foydalanuvchining to'xtab qolgan anketa holati tozalanadi
    va unga natija aytiladi (u rahmat xabarini olmagan bo'lishi mumkin).
    """
    done = 0
    for app in await get_undelivered_applications():
        text = anketa_for_admins(app["anketa"], app["phone"])
        results = await asyncio.gather(
            *(
                safe_send(bot=bot, chat_id=a, text=text, reply_markup=action_inline(app["id"]))
                for a in await reviewer_ids(bot, app["group_id"])
            )
        )
        delivered = any(results)
        if delivered:
            await mark_admins_notified(app["id"])
        else:
            await change_status(app["id"], old="pending", new="failed")
        logger.info("Ariza %s: adminlarga qayta yuborildi: %s", app["id"], delivered)

        user_state = get_private_state(storage=storage, bot=bot, user_id=app["user_id"])
        if await user_state.get_state() == Form.join_group.state:
            await user_state.clear()
            await safe_send(bot=bot, chat_id=app["user_id"], text=THANKS if delivered else ERROR_GENERIC)
        done += 1
    return done
