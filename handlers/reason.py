from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message, ReplyKeyboardRemove

from database import get_pending_reason, set_vote_reason
from texts import MODERATION_WARNING, SKIP_BUTTON
from utils.admin import is_admin
from utils.moderation import is_abusive

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
    if is_admin(message.from_user.id) and message.text.strip() == SKIP_BUTTON:
        # o'tkazib yuborildi: bo'sh sabab "javob berilgan" degani, qayta so'ralmaydi va xulosaga kirmaydi
        await set_vote_reason(app_id, message.from_user.id, "")
        await message.answer("Yaxshi, o'tkazib yuborildi 👌", reply_markup=ReplyKeyboardRemove())
        return

    if await is_abusive(message.text):
        await message.answer(MODERATION_WARNING)
        return

    await set_vote_reason(app_id, message.from_user.id, message.text)
    # sabab saqlanadi: ovoz berish tugagach AI uni boshqalar bilan umumlashtirib, rad etilgan arizachiga yuboradi (utils/voting.py)
    await message.answer("Rahmat, fikringiz qabul qilindi 🙏", reply_markup=ReplyKeyboardRemove())
