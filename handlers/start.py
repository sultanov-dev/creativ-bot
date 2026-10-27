from html import escape

from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import get_pending_reason
from utils.admin import is_admin
from handlers.profile import show_review
from states import Form
from utils.questions import question_for

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    # anketa yarim qolgan bo'lsa, to'xtagan savolni qayta beramiz
    current = await state.get_state() or ""
    if current in (Form.review.state, Form.pick_field.state):
        await show_review(bot, message.chat.id, state)
        return
    question = question_for(current)
    if question:
        text, markup = question
        await message.answer("Anketani to'ldirishda davom etamiz 👇")
        await message.answer(text, reply_markup=markup)
        return

    name = escape(message.from_user.full_name) if message.from_user is not None else ""
    await message.answer(f"Salom, {name}! Men Choyxona botiman ☕ Xush kelibsiz!")

    if message.from_user is None:
        return

    # ovoz berganda shaxsiy xabar yuborib bo'lmagan bo'lsa, sababni shu yerda so'raymiz
    pending = None if is_admin(message.from_user.id) else await get_pending_reason(message.from_user.id)
    if pending:
        await message.answer(
            f"Siz <b>{escape(pending['applicant_name'])}</b> arizasiga 👎 bergansiz.\n"
            "Qaroringiz sababini qisqacha yozib yuborsangiz, minnatdor bo'lamiz:"
        )
