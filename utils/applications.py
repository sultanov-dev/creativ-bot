import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from config import VOTING_MINUTES
from database import (
    change_status,
    create_application,
    get_active_application,
    get_undelivered_applications,
    mark_admins_notified,
    save_profile,
    set_vote_message,
    start_voting,
)
from aiogram.fsm.storage.base import BaseStorage

from keyboards.action import action_inline
from keyboards.vote import vote_inline
from states import Form
from texts import ALREADY_APPLIED, ERROR_GENERIC, THANKS, VOTE_DEADLINE
from utils.admin import reviewer_ids, safe_send
from utils.form_anketa import PROFILE_FIELDS, anketa_for_admins, format_anketa, full_name_of
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


async def submit_application(message: Message, bot: Bot, state: FSMContext) -> None:
    """Tekshiruvdan o'tgan anketa (yangi yoki saqlangan): ariza yaratiladi va adminlarga yuboriladi (guruh ovoziga
    faqat admin "Ovozga qo'yish"ni bossa chiqadi), holat ENG OXIRIDA tozalanadi.

    Bot shu oraliqda to'xtasa, holat va javoblar saqlanib qoladi: "Tasdiqlash" qayta bosilganda shu ariza
    qayta ishlatiladi va adminlarga yetkaziladi (javoblar yo'qolmaydi, ariza adminlarsiz qolib ketmaydi).
    """
    if message.from_user is not None:
        # username so'ralmaydi: avtomatik olinadi va anketada ko'rsatilmaydi
        await state.update_data(username=message.from_user.username)
    data = await state.get_data()
    group_id = data.get("group_id")
    user_id = message.chat.id

    # anketa saqlanadi: shu foydalanuvchi qayta qo'shilsa, savollar takrorlanmaydi (eski first/last_name -> full_name)
    await save_profile(user_id, {**{k: data.get(k) for k in PROFILE_FIELDS}, "full_name": full_name_of(data)})

    if group_id is None:
        logger.warning("group_id topilmadi, user_id=%s", user_id)
        await state.clear()
        await message.answer(ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    admins = await reviewer_ids(bot, group_id)
    if not admins:
        logger.error("Guruh %s uchun anketani ko'rib chiqadigan admin topilmadi", group_id)
        await state.clear()
        await message.answer(ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    full_name = full_name_of(data)
    # guruhga (ovoz berish xabari) ketadigan variant telefonsiz; adminlar va arizachi telefonni ko'radi
    anketa = format_anketa(data)
    private_anketa = format_anketa(data, with_phone=True)

    existing = await get_active_application(user_id, group_id)
    # faqat aynan shu anketadan yaratilgan pending ariza qayta ishlatiladi (oldingi urinish yiqilgan); boshqasi dublikat
    if existing and not (existing["status"] == "pending" and existing["anketa"] == anketa):
        await state.clear()
        await message.answer(ALREADY_APPLIED, reply_markup=ReplyKeyboardRemove())
        return
    # holat hali tozalanmagan bo'lsa, oldingi urinish tugamagan: o'sha ariza qayta ishlatiladi
    app_id = existing["id"] if existing else await create_application(
        user_id,
        group_id,
        full_name,
        anketa,
        first_name=data.get("first_name"),  # eski saqlangan profillarda
        last_name=data.get("last_name"),
        tg_username=data.get("username"),
        phone=data.get("phone"),
        admins_notified=False,  # adminlarga yetgach belgilanadi; yetmay qolsa, startda qayta yuboriladi
    )
    if app_id is None:
        await state.clear()
        await message.answer(ALREADY_APPLIED, reply_markup=ReplyKeyboardRemove())
        return

    results = await asyncio.gather(
        *(
            safe_send(
                bot=bot,
                chat_id=admin_id,
                text=private_anketa,
                reply_markup=action_inline(app_id),
            )
            for admin_id in admins
        )
    )

    if not any(results):
        # hech kim ko'ra olmasa, ariza osilib qolmasligi uchun yopamiz: foydalanuvchi qayta urinishi mumkin
        logger.warning(
            "Hech bir admin anketani olmadi (botni start qilmagan bo'lishi mumkin)"
        )
        await change_status(app_id, old="pending", new="failed")
        await state.clear()
        await message.answer(ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    await mark_admins_notified(app_id)
    await state.clear()  # eng oxirida: yuqoridagi qadamlar yiqilsa, javoblar yo'qolmaydi
    await message.answer(THANKS, reply_markup=ReplyKeyboardRemove())


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
        if await user_state.get_state() in (Form.join_group.state, Form.confirm.state):
            await user_state.clear()
            await safe_send(bot=bot, chat_id=app["user_id"], text=THANKS if delivered else ERROR_GENERIC)
        done += 1
    return done
