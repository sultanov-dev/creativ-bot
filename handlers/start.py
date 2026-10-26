from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import get_pending_reason
from utils.questions import question_for

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    # anketa yarim qolgan bo'lsa, to'xtagan savolni qayta beramiz
    question = question_for(await state.get_state() or "")
    if question:
        text, markup = question
        await message.answer("Anketani to'ldirishni davom ettiramiz 👇")
        await message.answer(text, reply_markup=markup)
        return

    name = escape(message.from_user.full_name) if message.from_user is not None else ""
    await message.answer(f"Salom, {name}! Men Choyxona botiman ☕")

    if message.from_user is None:
        return

    # ovoz berganda lichkaga yozib bo'lmagan bo'lsa, sababni shu yerda so'raymiz
    pending = await get_pending_reason(message.from_user.id)
    if pending:
        await message.answer(
            f"Siz <b>{escape(pending['applicant_name'])}</b> arizasiga 👎 bergansiz. "
            "Nima uchun \"yo'q\" dedingiz? Sababini yozing:"
        )
