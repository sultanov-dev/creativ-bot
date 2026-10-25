from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from callbacks import ApplicantCB
from utils.admin import is_group_admin, mark_done, safe_send

router = Router()


@router.callback_query(ApplicantCB.filter(F.action == "reject"))
async def reject(call: CallbackQuery, callback_data: ApplicantCB, bot: Bot):
    if not await is_group_admin(
        bot=bot, chat_id=callback_data.group_id, user_id=call.from_user.id
    ):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    try:
        await bot.decline_chat_join_request(
            chat_id=callback_data.group_id, user_id=callback_data.user_id
        )
    except TelegramBadRequest:
        await call.answer("Bu ariza allaqachon ko'rib chiqilgan", show_alert=True)
        await mark_done(
            call=call,
            result="⚠️ Allaqachon ko'rib chiqilgan",
            bot=bot,
            chat_id=callback_data.group_id,
            user_id=call.from_user.id,
        )
        return

    await call.answer("Rad etildi!")
    await mark_done(
        call=call,
        result="❌ Rad etildi",
        bot=bot,
        chat_id=callback_data.group_id,
        user_id=call.from_user.id,
    )
    await safe_send(
        bot=bot, chat_id=callback_data.user_id, text="Arizangiz rad etildi!"
    )


@router.callback_query(ApplicantCB.filter(F.action == "accept"))
async def accept(call: CallbackQuery, callback_data: ApplicantCB, bot: Bot):
    if not await is_group_admin(
        bot, chat_id=callback_data.group_id, user_id=call.from_user.id
    ):
        await call.answer("Siz admin emassiz!", show_alert=True)
        return

    # TODO guruhda ovozga qo'yildi

    await call.answer(
        text="Arizangiz guruh a'zolari o'rtasida ovoz berishga yuborildi!"
    )
    await mark_done(
        call=call,
        result="🗳 Ovoz berishga yuborildi",
        bot=bot,
        chat_id=callback_data.group_id,
        user_id=call.from_user.id,
    )
    await safe_send(
        bot=bot,
        chat_id=callback_data.user_id,
        text="Arizangiz guruh a'zolari o'rtasida ovoz berishga yuborildi! Natijani kuting ⏳",
    )
