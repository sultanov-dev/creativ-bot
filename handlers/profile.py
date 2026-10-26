import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from callbacks import ProfileCB
from database import save_profile
from keyboards.profile import FIELD_LABELS, fields_inline, review_inline
from states import Form
from texts import (
    PROFILE_BUTTON_STALE,
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
router.callback_query.filter(F.message.chat.type == "private")
logger = logging.getLogger(__name__)


async def show_review(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Saqlangan anketani ko'rsatadi: "O'zgartirish" yoki "Shunday qoldirish"."""
    data = await state.get_data()
    await bot.send_message(
        chat_id=chat_id,
        text=PROFILE_REVIEW.format(anketa=format_anketa(data, with_phone=True)),
        reply_markup=review_inline(),
    )


async def finish_edit(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Bitta maydon o'zgartirilgach: yangi ma'lumot saqlanadi va anketa qayta ko'rsatiladi."""
    await state.update_data(editing=False)
    data = await state.get_data()
    await save_profile(chat_id, {k: data.get(k) for k in PROFILE_FIELDS})
    await state.set_state(Form.review)
    # savolda reply klaviatura (o'tkazib yuborish/telefon) bo'lgan bo'lsa, uni olib tashlaymiz
    await bot.send_message(chat_id=chat_id, text=PROFILE_SAVED, reply_markup=ReplyKeyboardRemove())
    await show_review(bot, chat_id, state)


async def _strip_buttons(call: CallbackQuery) -> None:
    if isinstance(call.message, Message):
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:  # xabar o'zgarmagan yoki eskirgan: muhim emas
            pass


@router.callback_query(ProfileCB.filter(), ~StateFilter(Form.review))
async def stale(call: CallbackQuery):
    await call.answer(PROFILE_BUTTON_STALE, show_alert=True)


@router.callback_query(ProfileCB.filter(F.action == "edit"))
async def on_edit(call: CallbackQuery):
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.edit_text(PROFILE_PICK_FIELD, reply_markup=fields_inline())


@router.callback_query(ProfileCB.filter(F.action == "back"))
async def on_back(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if isinstance(call.message, Message):
        data = await state.get_data()
        await call.message.edit_text(
            PROFILE_REVIEW.format(anketa=format_anketa(data, with_phone=True)),
            reply_markup=review_inline(),
        )


@router.callback_query(ProfileCB.filter(F.action == "field"))
async def on_field(call: CallbackQuery, callback_data: ProfileCB, bot: Bot, state: FSMContext):
    field = callback_data.field
    if field not in FIELD_LABELS:
        await call.answer()
        return
    await call.answer()
    await _strip_buttons(call)
    await state.update_data(editing=True)
    await state.set_state(getattr(Form, field))
    await ask(bot, call.from_user.id, getattr(Form, field), delay=0.5)


@router.callback_query(ProfileCB.filter(F.action == "keep"))
async def on_keep(call: CallbackQuery, bot: Bot, state: FSMContext):
    data = await state.get_data()
    group_id = data.get("group_id")
    await call.answer()
    await _strip_buttons(call)
    await state.clear()
    if group_id is None:
        logger.warning("group_id topilmadi, user_id=%s", call.from_user.id)
        return
    profile = {k: data.get(k) for k in PROFILE_FIELDS}
    await apply_from_profile(bot, call.from_user.id, group_id, call.from_user.id, profile)


@router.message(StateFilter(Form.review))
async def review_text(message: Message):
    await message.answer(PROFILE_USE_BUTTONS)
