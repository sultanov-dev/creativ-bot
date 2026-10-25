from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from database import get_pending_reason

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Salom, {message.from_user.full_name if message.from_user is not None else None}! Men Choyxona botiman ☕"
    )

    if message.from_user is None:
        return

    # ovoz berganda lichkaga yozib bo'lmagan bo'lsa, sababni shu yerda so'raymiz
    pending = await get_pending_reason(message.from_user.id)
    if pending:
        await message.answer(
            f"Siz <b>{escape(pending['applicant_name'])}</b> arizasiga 👎 bergansiz. "
            "Nima uchun \"yo'q\" dedingiz? Sababini yozing:"
        )
