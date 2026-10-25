from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from callbacks import VoteCB
from config import REQUIRED_VOTES
from database import add_vote, change_status, count_votes, get_application
from keyboards.vote import vote_inline
from utils.admin import get_user_status, safe_send

router = Router()

VOTER_STATUSES = (
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.RESTRICTED,
)


async def _finish(call: CallbackQuery, result: str) -> None:
    if isinstance(call.message, Message):
        try:
            await call.message.edit_text(f"{call.message.html_text}\n\n{result}")
        except TelegramBadRequest:
            pass


@router.callback_query(VoteCB.filter())
async def on_vote(call: CallbackQuery, callback_data: VoteCB, bot: Bot):
    app = await get_application(callback_data.app_id)

    if app is None or app["status"] != "voting":
        await call.answer(text="Ariza berish allaqachon yakunlangan", show_alert=True)
        return

    if callback_data.vote not in ("yes", "no"):
        await call.answer()
        return

    group_id = app["group_id"]
    applicant_id = app["user_id"]
    voter_id = call.from_user.id

    if voter_id == applicant_id:
        await call.answer("O'zingizning arizangizga ovoz bera olmaysiz", show_alert=True)
        return

    if await get_user_status(bot, group_id, voter_id) not in VOTER_STATUSES:
        await call.answer("Faqat guruh a'zolari ovoz bera oladi", show_alert=True)
        return

    if not await add_vote(app["id"], voter_id, callback_data.vote):
        await call.answer("Siz allaqachon ovoz bergansiz", show_alert=True)
        return

    yes, no = await count_votes(app["id"])

    if yes >= REQUIRED_VOTES:
        if await change_status(app["id"], old="voting", new="accepted"):
            try:
                await bot.approve_chat_join_request(chat_id=group_id, user_id=applicant_id)
            except TelegramBadRequest:
                # so'rov muddati o'tgan yoki foydalanuvchi allaqachon a'zo
                pass
            await _finish(call, f"✅ Qabul qilindi ({yes} 👍 / {no} 👎)")
            await safe_send(
                bot=bot,
                chat_id=applicant_id,
                text="Tabriklaymiz, arizangiz qabul qilindi! 🎉",
            )
        await call.answer("Ovozingiz qabul qilindi")
        return

    if no >= REQUIRED_VOTES:
        if await change_status(app["id"], old="voting", new="rejected"):
            try:
                await bot.decline_chat_join_request(chat_id=group_id, user_id=applicant_id)
            except TelegramBadRequest:
                pass
            await _finish(call, f"❌ Rad etildi ({yes} 👍 / {no} 👎)")
            await safe_send(
                bot=bot,
                chat_id=applicant_id,
                text="Afsuski, guruh a'zolari arizangizni rad etishdi.",
            )
        await call.answer("Ovozingiz qabul qilindi")
        return

    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(
                reply_markup=vote_inline(app["id"], yes=yes, no=no)
            )
        except TelegramBadRequest:
            pass

    await call.answer("Ovozingiz qabul qilindi")
