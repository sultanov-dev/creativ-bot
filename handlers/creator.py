from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from callbacks import CreatorCB
from database import change_status, get_application
from utils.admin import get_user_status, safe_send

router = Router()


@router.callback_query(CreatorCB.filter())
async def on_creator_decision(call: CallbackQuery, callback_data: CreatorCB, bot: Bot):
    """Ovoz berish tugagach oxirgi qaror: faqat guruh creatori hal qiladi (ovoz natijasidan qat'i nazar)."""
    if callback_data.action not in ("accept", "reject"):
        await call.answer()
        return

    app = await get_application(callback_data.app_id)
    if app is None:
        await call.answer("Ariza topilmadi", show_alert=True)
        return

    group_id = app["group_id"]
    user_id = app["user_id"]

    if await get_user_status(bot, group_id, call.from_user.id) != ChatMemberStatus.CREATOR:
        await call.answer("Bu qarorni faqat guruh egasi qabul qiladi", show_alert=True)
        return

    accepted = callback_data.action == "accept"
    new = "accepted" if accepted else "rejected"
    if not await change_status(app["id"], old="creator_review", new=new):
        await call.answer("Bu ariza bo'yicha qaror allaqachon qabul qilingan", show_alert=True)
        return

    try:
        if accepted:
            await bot.approve_chat_join_request(chat_id=group_id, user_id=user_id)
        else:
            await bot.decline_chat_join_request(chat_id=group_id, user_id=user_id)
    except TelegramAPIError:
        pass  # so'rov muddati o'tgan yoki foydalanuvchi allaqachon a'zo

    result = "✅ Qabul qilindi" if accepted else "❌ Rad etildi"
    await call.answer(result)
    if isinstance(call.message, Message):
        try:
            await call.message.edit_text(f"{call.message.html_text}\n\n{result}")
        except TelegramAPIError:
            pass

    await safe_send(
        bot=bot,
        chat_id=user_id,
        text=(
            "Tabriklaymiz, arizangiz qabul qilindi! 🎉"
            if accepted
            else "Afsuski, arizangiz rad etildi."
        ),
    )
