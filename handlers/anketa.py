import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import create_application
from keyboards.action import action_inline
from states import Form
from texts import (
    ASK_ABOUT,
    ASK_JOB,
    ASK_REASON,
    ERROR_GENERIC,
    ONLY_TEXT,
    THANKS,
    WRONG_AGE,
)
from utils.admin import safe_send
from utils.form_anketa import format_anketa
from utils.num_matcher import extract_number
from utils.typing import send_typing

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)


@router.message(F.text, Form.age)
async def capture_age(message: Message, bot: Bot, state: FSMContext):
    age = extract_number(message.text)

    if not age or not (10 <= age <= 100):
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
async def capture_join_group(message: Message, bot: Bot, state: FSMContext):
    await state.update_data(join_group=message.text)
    data = await state.get_data()
    group_id = data.get("group_id")
    user_id = message.chat.id
    await state.clear()

    user = message.from_user
    anketa = format_anketa(user.full_name if user else "Unknown", data)

    if group_id is None:
        logger.warning("group_id topilmadi, user_id=%s", user_id)
        await message.answer(ERROR_GENERIC)
        return

    try:
        admins = await bot.get_chat_administrators(chat_id=group_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        logger.exception("Adminlar ro'yxatini olib bo'lmadi, group_id=%s", group_id)
        await message.answer(ERROR_GENERIC)
        return

    await message.answer(anketa)
    await message.answer(THANKS)

    sent = 0
    app_id = await create_application(
        user_id, group_id, user.full_name if user else "Unknown", anketa
    )

    for admin in admins:
        if admin.user.is_bot:
            continue

        if await safe_send(
            bot=bot,
            chat_id=admin.user.id,
            text=anketa,
            reply_markup=action_inline(app_id),
        ):
            sent += 1

    if sent == 0:
        logger.warning(
            "Hech bir admin anketani olmadi (botni start qilmagan bo'lishi mumkin)"
        )


@router.message(StateFilter(Form))
async def not_text(message: Message):
    await message.answer(ONLY_TEXT)
