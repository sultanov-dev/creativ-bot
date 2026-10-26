from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from database import get_pending_reason, set_vote_reason

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(F.text, ~F.text.startswith("/"), StateFilter(None))
async def capture_reason(message: Message):
    if message.from_user is None or message.text is None:
        return

    pending = await get_pending_reason(message.from_user.id)
    if pending is None:
        return

    app_id = pending["app_id"]
    await set_vote_reason(app_id, message.from_user.id, message.text)
    # sabab saqlanadi: ovoz berish tugagach AI uni boshqalar bilan umumlashtirib, rad etilgan arizachiga yuboradi (utils/voting.py)
    await message.answer(
        "Rahmat, fikringiz qabul qilindi 🙏"
    )
