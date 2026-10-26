import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import change_status, create_application, get_active_application
from keyboards.action import action_inline
from states import Form
from texts import (
    ALREADY_APPLIED,
    ASK_ABOUT,
    ASK_JOB,
    ASK_REASON,
    ERROR_GENERIC,
    ONLY_TEXT,
    THANKS,
    TOO_LONG,
    WRONG_AGE,
)
from utils.admin import safe_send
from utils.form_anketa import format_anketa
from utils.num_matcher import extract_number
from utils.typing import send_typing

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)

# 3 ta javob + ism Telegram'ning 4096 belgilik xabar chegarasiga sig'ishi uchun
MAX_ANSWER_LEN = 800


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
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    await state.update_data(job=message.text)
    await state.set_state(Form.about)

    await send_typing(bot=bot, chat_id=message.chat.id, text=ASK_ABOUT, delay=2.0)


@router.message(F.text, Form.about)
async def capture_about(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    await state.update_data(about=message.text)
    await state.set_state(Form.join_group)

    await send_typing(bot=bot, chat_id=message.chat.id, text=ASK_REASON, delay=2.0)


@router.message(F.text, Form.join_group)
async def capture_join_group(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

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

    if await get_active_application(user_id, group_id):
        await message.answer(ALREADY_APPLIED)
        return

    app_id = await create_application(
        user_id, group_id, user.full_name if user else "Unknown", anketa
    )
    if app_id is None:
        await message.answer(ALREADY_APPLIED)
        return

    results = await asyncio.gather(
        *(
            safe_send(
                bot=bot,
                chat_id=admin.user.id,
                text=anketa,
                reply_markup=action_inline(app_id),
            )
            for admin in admins
            if not admin.user.is_bot
        )
    )

    if not any(results):
        # hech kim ko'ra olmasa, ariza osilib qolmasligi uchun yopamiz: foydalanuvchi qayta urinishi mumkin
        logger.warning(
            "Hech bir admin anketani olmadi (botni start qilmagan bo'lishi mumkin)"
        )
        await change_status(app_id, old="pending", new="failed")
        await message.answer(ERROR_GENERIC)
        return

    await message.answer(anketa)
    await message.answer(THANKS)


@router.message(StateFilter(Form))
async def not_text(message: Message):
    await message.answer(ONLY_TEXT)
