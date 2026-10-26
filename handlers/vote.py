from datetime import datetime, timezone
from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from callbacks import VoteCB
from config import ADMIN_VOTE_WEIGHT
from database import add_vote, count_votes, get_application
from keyboards.vote import vote_inline
from utils.admin import is_group_admin, is_group_member, safe_send

router = Router()


def utcnow_str() -> str:
    # SQLite datetime('now') bilan bir xil format
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@router.callback_query(VoteCB.filter())
async def on_vote(call: CallbackQuery, callback_data: VoteCB, bot: Bot):
    app = await get_application(callback_data.app_id)

    if app is None or app["status"] != "voting":
        await call.answer(text="Ariza berish allaqachon yakunlangan", show_alert=True)
        return

    if callback_data.vote not in ("yes", "no"):
        await call.answer()
        return

    if app["voting_ends_at"] and app["voting_ends_at"] <= utcnow_str():
        await call.answer("Ovoz berish muddati tugadi, natija tez orada e'lon qilinadi", show_alert=True)
        return

    group_id = app["group_id"]
    applicant_id = app["user_id"]
    voter_id = call.from_user.id

    if voter_id == applicant_id:
        await call.answer("O'zingizning arizangizga ovoz bera olmaysiz", show_alert=True)
        return

    if not await is_group_member(bot, group_id, voter_id):
        await call.answer("Faqat guruh a'zolari ovoz bera oladi", show_alert=True)
        return

    weight = ADMIN_VOTE_WEIGHT if await is_group_admin(bot, group_id, voter_id) else 1
    if not await add_vote(app["id"], voter_id, callback_data.vote, weight):
        await call.answer("Siz allaqachon ovoz bergansiz", show_alert=True)
        return

    note, alert = "Ovozingiz qabul qilindi", False
    if weight > 1:
        note = f"Ovozingiz qabul qilindi (admin ovozi: {weight} ta ovozga teng)"
    if callback_data.vote == "no":
        asked = await safe_send(
            bot=bot,
            chat_id=voter_id,
            text=(
                f"Siz <b>{escape(app['full_name'])}</b> arizasiga 👎 berdingiz.\n"
                "Nima uchun \"yo'q\" dedingiz? Sababini yozib yuboring:"
            ),
        )
        if not asked:
            note = (
                "Sababini aytish uchun botga lichkada /start bosing, "
                "so'ng sababni yozing."
            )
            alert = True

    yes, no = await count_votes(app["id"])

    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(
                reply_markup=vote_inline(app["id"], yes=yes, no=no)
            )
        except TelegramAPIError:
            # flood limit yoki o'zgarmagan markup: ovoz baribir yozilgan
            pass

    await call.answer(note, show_alert=alert)
