from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery

from callbacks import ApplicantCB
from config import ADMIN_VOTE_WEIGHT, VOTING_MINUTES
from database import change_status, get_application, set_vote_message, start_voting
from keyboards.vote import vote_inline
from utils.admin import is_group_admin, mark_done, safe_send

router = Router()


@router.callback_query(ApplicantCB.filter(F.action == "reject"))
async def reject(call: CallbackQuery, callback_data: ApplicantCB, bot: Bot):
    app = await get_application(callback_data.app_id)

    if app is None:
        await call.answer("Ariza topilmadi", show_alert=True)
        return

    group_id = app["group_id"]
    user_id = app["user_id"]

    if not await is_group_admin(bot=bot, chat_id=group_id, user_id=call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    if not await change_status(app_id=app["id"], old="pending", new="rejected"):
        await call.answer("Bu ariza allaqachon ko'rib chiqilgan", show_alert=True)
        await mark_done(
            call=call,
            result="⚠️ Allaqachon ko'rib chiqilgan",
            bot=bot,
            chat_id=group_id,
            user_id=call.from_user.id,
        )
        return

    try:
        await bot.decline_chat_join_request(chat_id=group_id, user_id=user_id)
    except TelegramBadRequest:
        pass

    await call.answer("Rad etildi!")
    await mark_done(
        call=call,
        result="❌ Rad etildi",
        bot=bot,
        chat_id=group_id,
        user_id=call.from_user.id,
    )
    await safe_send(bot=bot, chat_id=user_id, text="Afsuski arizangiz rad etildi!")


@router.callback_query(ApplicantCB.filter(F.action == "accept"))
async def accept(call: CallbackQuery, callback_data: ApplicantCB, bot: Bot):
    app = await get_application(callback_data.app_id)

    if app is None:
        await call.answer("Ariza topilmadi", show_alert=True)
        return

    group_id = app["group_id"]
    user_id = app["user_id"]

    if not await is_group_admin(bot, chat_id=group_id, user_id=call.from_user.id):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    if not await start_voting(app["id"], VOTING_MINUTES):
        await call.answer("Bu ariza allaqachon ko'rib chiqilgan", show_alert=True)
        await mark_done(
            call=call,
            result="⚠️ Allaqachon ko'rib chiqilgan",
            bot=bot,
            chat_id=group_id,
            user_id=call.from_user.id,
        )
        return

    try:
        vote_msg = await bot.send_message(
            chat_id=group_id,
            text=(
                "🗳 <b>Yangi a'zo uchun ovoz berish</b>\n\n"
                f"{app['anketa']}\n\n"
                f"⏳ Ovoz berish <b>{VOTING_MINUTES}</b> daqiqa davom etadi. "
                "Muddat tugagach ovozlar guruh egasiga yuboriladi va "
                "oxirgi qarorni guruh egasi qabul qiladi.\n"
                f"Guruh adminining ovozi <b>{ADMIN_VOTE_WEIGHT}</b> ta ovozga teng."
            ),
            reply_markup=vote_inline(app_id=app["id"]),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        # xabar yuborilmasa, ariza qayta ko'rib chiqilishi uchun holatni qaytaramiz
        await change_status(app_id=app["id"], old="voting", new="pending")
        await call.answer(
            "Ovoz berish xabarini guruhga yuborib bo'lmadi", show_alert=True
        )
        return
    await set_vote_message(app_id=app["id"], message_id=vote_msg.message_id)

    await call.answer(
        text="Arizangiz guruh a'zolari o'rtasida ovoz berishga yuborildi!"
    )
    await mark_done(
        call=call,
        result="🗳 Ovoz berishga yuborildi",
        bot=bot,
        chat_id=group_id,
        user_id=call.from_user.id,
    )
    await safe_send(
        bot=bot,
        chat_id=user_id,
        text="Arizangiz guruh a'zolari o'rtasida ovoz berishga yuborildi! Natijani kuting ⏳",
    )
