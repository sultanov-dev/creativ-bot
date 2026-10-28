from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import get_pending_reason
from keyboards.skip import skip_keyboard
from utils.admin import is_reviewer
from utils.reason_text import reason_question
from handlers.profile import show_review
from handlers.support import resume_support
from states import Form
from utils.questions import question_for

router = Router()
router.message.filter(F.chat.type == "private")  # guruhdagi "/start" ham begona buyruq: group.strangers e'tiborsiz qoldirib o'chiradi


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
    # anketa yarim qolgan bo'lsa, to'xtagan savolni qayta beramiz
    current = await state.get_state() or ""
    if current in (Form.review.state, Form.confirm.state, Form.pick_field.state):
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
    pending = await get_pending_reason(message.from_user.id)
    if pending:
        await message.answer(
            reason_question(pending["applicant_name"]),
            reply_markup=skip_keyboard() if await is_reviewer(bot, pending["group_id"], message.from_user.id) else None,
        )

    # guruhda admin bilan gaplashmoqchi bo'lib, botga /start bosmagan bo'lsa: suhbat shu yerdan boshlanadi
    await resume_support(bot, message.from_user.id)
