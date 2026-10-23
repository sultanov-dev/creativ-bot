from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from states import Form
from texts import ASK_ABOUT, ASK_JOB, ASK_REASON, ONLY_TEXT, WRONG_AGE
from utils.form_anketa import format_anketa
from utils.num_matcher import extract_number
from utils.typing import send_typing

router = Router()
router.message.filter(F.chat.type == "private")


@router.message(F.text, Form.age)
async def capture_age(message: Message, bot: Bot, state: FSMContext):
    age = extract_number(message.text)

    if not age or not (1 <= age <= 100):
        await message.reply(WRONG_AGE)
        return

    await state.update_data(age=age)
    await state.set_state(Form.job)

    await send_typing(bot=bot, chat_id=message.chat.id, text=ASK_JOB, delay=2.0)


@router.message(F.text, Form.job)
async def capture_job(message: Message, bot: Bot, state: FSMContext):
    await state.update_data(job=message.text)
    await state.set_state(Form.about)

    await send_typing(bot=bot, chat_id=message.chat.id, text=ASK_ABOUT, delay=2.0)


@router.message(F.text, Form.about)
async def capture_about(message: Message, bot: Bot, state: FSMContext):
    await state.update_data(about=message.text)
    await state.set_state(Form.join_group)

    await send_typing(bot=bot, chat_id=message.chat.id, text=ASK_REASON, delay=2.0)


@router.message(F.text, Form.join_group)
async def capture_join_group(message: Message, state: FSMContext):
    await state.update_data(join_group=message.text)
    data = await state.get_data()

    user = message.from_user
    anketa = format_anketa(user.full_name if user else "Unknown", data)

    await state.clear()
    await message.answer(anketa)

    # Adminga anketani yuborish


@router.message(StateFilter(Form))
async def not_text(message: Message):
    await message.answer(ONLY_TEXT)
