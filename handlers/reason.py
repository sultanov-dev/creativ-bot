from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from database import get_application, get_pending_reason, set_vote_reason
from utils.reasons import send_to_admins

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(F.text, ~F.text.startswith("/"), StateFilter(None))
async def capture_reason(message: Message, bot: Bot):
    if message.from_user is None or message.text is None:
        return

    pending = await get_pending_reason(message.from_user.id)
    if pending is None:
        return

    app_id = pending["app_id"]
    await set_vote_reason(app_id, message.from_user.id, message.text)
    await message.answer("Rahmat, javobingiz adminlarga yetkaziladi 🙏")

    app = await get_application(app_id)
    if app is not None:
        await send_to_admins(
            bot,
            app["group_id"],
            f"📋 <b>{escape(app['full_name'])}</b> arizasi bo'yicha 👎 sababi\n"
            f"• <b>{escape(message.from_user.full_name)}</b>: {escape(message.text)}",
        )
