from datetime import datetime, timezone
from html import escape

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from callbacks import VoteCB
from config import ADMIN_VOTE_WEIGHT
from database import add_vote, get_application, get_vote
from utils.admin import is_group_admin, is_group_member, safe_send

router = Router()

VOTE_LABELS = {"yes": "👍 Ha", "no": "👎 Yo'q"}


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
        previous = await get_vote(app["id"], voter_id)
        await call.answer(
            f"Siz allaqachon «{VOTE_LABELS.get(previous, '?')}» deb ovoz bergansiz. "
            "Ovozni o'zgartirib bo'lmaydi.",
            show_alert=True,
        )
        return

    # tugmalar hamma uchun bir xil, shuning uchun tanlovni ogohlantirish oynasida aniq ko'rsatamiz
    chosen = VOTE_LABELS[callback_data.vote]
    note, alert = f"✅ Siz «{chosen}» deb ovoz berdingiz. Ovozingiz qabul qilindi.", True
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
                f"✅ Siz «{chosen}» deb ovoz berdingiz.\n"
                "Sababini aytish uchun botga lichkada /start bosing, so'ng sababni yozing."
            )

    await call.answer(note, show_alert=alert)
