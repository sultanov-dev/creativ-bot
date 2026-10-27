import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from database import save_profile
from keyboards.profile import FIELD_BY_LABEL, fields_keyboard, review_keyboard
from states import Form
from texts import (
    PROFILE_BACK_BUTTON,
    PROFILE_EDIT_BUTTON,
    PROFILE_KEEP_BUTTON,
    PROFILE_PICK_FIELD,
    PROFILE_REVIEW,
    PROFILE_SAVED,
    PROFILE_USE_BUTTONS,
)
from utils.applications import apply_from_profile
from utils.form_anketa import PROFILE_FIELDS, format_anketa
from utils.questions import ask

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)


async def show_review(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Saqlangan anketani ko'rsatadi: "O'zgartirish" yoki "Shunday qoldirish" (oddiy tugmalar)."""
    data = await state.get_data()
    await state.set_state(Form.review)
    await bot.send_message(
        chat_id=chat_id,
        text=PROFILE_REVIEW.format(anketa=format_anketa(data, with_phone=True)),
        reply_markup=review_keyboard(),
    )


async def finish_edit(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Bitta maydon o'zgartirilgach: yangi ma'lumot saqlanadi va anketa qayta ko'rsatiladi."""
    await state.update_data(editing=False)
    data = await state.get_data()
    await save_profile(chat_id, {k: data.get(k) for k in PROFILE_FIELDS})
    await bot.send_message(chat_id=chat_id, text=PROFILE_SAVED)
    await show_review(bot, chat_id, state)


@router.message(F.text == PROFILE_EDIT_BUTTON, StateFilter(Form.review))
async def on_edit(message: Message, state: FSMContext):
    await state.set_state(Form.pick_field)
    await message.answer(PROFILE_PICK_FIELD, reply_markup=fields_keyboard())


@router.message(F.text == PROFILE_BACK_BUTTON, StateFilter(Form.pick_field))
async def on_back(message: Message, bot: Bot, state: FSMContext):
    await show_review(bot, message.chat.id, state)


@router.message(F.text.in_(FIELD_BY_LABEL), StateFilter(Form.pick_field))
async def on_field(message: Message, bot: Bot, state: FSMContext):
    field = FIELD_BY_LABEL[message.text or ""]
    await state.update_data(editing=True)
    await state.set_state(getattr(Form, field))
    await ask(bot, message.chat.id, getattr(Form, field), delay=0.5)


@router.message(F.text == PROFILE_KEEP_BUTTON, StateFilter(Form.review))
async def on_keep(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    group_id = data.get("group_id")
    await state.clear()
    if group_id is None:
        logger.warning("group_id topilmadi, user_id=%s", message.chat.id)
        await message.answer(PROFILE_SAVED, reply_markup=ReplyKeyboardRemove())
        return
    # eski profillarda ism first_name/last_name'da: full_name_of shularga tayanadi
    profile = {k: data.get(k) for k in (*PROFILE_FIELDS, "first_name", "last_name")}
    await apply_from_profile(bot, message.chat.id, group_id, message.chat.id, profile)


@router.message(StateFilter(Form.review, Form.pick_field))
async def use_buttons(message: Message):
    await message.answer(PROFILE_USE_BUTTONS)
