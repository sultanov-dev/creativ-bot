from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import get_pending_reason
from states import Form
from texts import ASK_ABOUT, ASK_AGE, ASK_JOB, ASK_REASON

router = Router()

QUESTIONS = {
    Form.age.state: ASK_AGE,
    Form.job.state: ASK_JOB,
    Form.about.state: ASK_ABOUT,
    Form.join_group.state: ASK_REASON,
}


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    # anketa yarim qolgan bo'lsa, to'xtagan savolni qayta beramiz
    question = QUESTIONS.get(await state.get_state() or "")
    if question:
        await message.answer("Anketani to'ldirishni davom ettiramiz 👇")
        await message.answer(question)
        return

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
