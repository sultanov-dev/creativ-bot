import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.utils.chat_action import ChatActionSender

from database import save_profile
from keyboards.profile import FIELD_BY_LABEL, FIELD_LABELS, confirm_keyboard, fields_keyboard, review_keyboard
from states import Form
from texts import (
    ANKETA_CONFIRM,
    ANKETA_NEEDS_FIX,
    ANKETA_REVIEW_UNAVAILABLE,
    PROFILE_BACK_BUTTON,
    PROFILE_EDIT_BUTTON,
    PROFILE_KEEP_BUTTON,
    PROFILE_PICK_FIELD,
    PROFILE_REVIEW,
    PROFILE_SAVED,
    PROFILE_USE_BUTTONS,
)
from utils.anketa_review import review_anketa
from utils.applications import apply_from_profile
from utils.form_anketa import PROFILE_FIELDS, format_anketa
from utils.questions import ask

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)


async def show_review(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Anketani ko'rsatadi (oddiy tugmalar bilan).

    Yangi to'ldirilgan anketa (`fresh`): "Tasdiqlash" / "O'zgartirish" (Form.confirm), adminlarga hali yuborilmagan.
    Avval saqlangan anketa: "O'zgartirish" / "Shunday qoldirish" (Form.review).
    """
    data = await state.get_data()
    anketa = format_anketa(data, with_phone=True)
    if data.get("fresh"):
        await state.set_state(Form.confirm)
        await bot.send_message(chat_id=chat_id, text=ANKETA_CONFIRM.format(anketa=anketa), reply_markup=confirm_keyboard())
        return
    await state.set_state(Form.review)
    await bot.send_message(
        chat_id=chat_id,
        text=PROFILE_REVIEW.format(anketa=anketa),
        reply_markup=review_keyboard(),
    )


async def _ask_field(bot: Bot, chat_id: int, state: FSMContext, field: str) -> None:
    """Bitta maydonni qayta so'raydi: javobdan keyin anketa._advance -> finish_edit."""
    await state.update_data(editing=True)
    await state.set_state(getattr(Form, field))
    await ask(bot, chat_id, getattr(Form, field), delay=0.5)


async def ai_check_passed(bot: Bot, chat_id: int, state: FSMContext) -> bool:
    """Tasdiqlangan anketani AI tekshiradi. Muammo bo'lsa: foydalanuvchiga sababi aytiladi va muammoli maydonlar
    birin-ketin qayta so'raladi (oxirida anketa yana ko'rsatiladi, tasdiqlansa yana tekshiriladi); False qaytadi.
    AI tekshira olmasa ham False: anketa tekshiruvsiz adminga o'tmaydi, holat o'zgarmaydi (tugmani keyinroq qayta bosadi)."""
    data = await state.get_data()
    async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
        problems = await review_anketa(data)
    if problems is None:
        keyboard = confirm_keyboard() if data.get("fresh") else review_keyboard()
        await bot.send_message(chat_id=chat_id, text=ANKETA_REVIEW_UNAVAILABLE, reply_markup=keyboard)
        return False
    if not problems:
        return True
    lines = "\n".join(f"• <b>{FIELD_LABELS[f]}</b>: {escape(reason)}" if reason else f"• <b>{FIELD_LABELS[f]}</b>"
                      for f, reason in problems.items())
    await bot.send_message(chat_id=chat_id, text=ANKETA_NEEDS_FIX.format(problems=lines), reply_markup=ReplyKeyboardRemove())
    first, *rest = problems
    await state.update_data(fix_fields=rest)
    await _ask_field(bot, chat_id, state, first)
    return False


async def finish_edit(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Bitta maydon o'zgartirilgach: AI ko'rsatgan navbatdagi maydon bo'lsa o'sha so'raladi, aks holda anketa qayta
    ko'rsatiladi. Avval saqlangan anketa (fresh emas) har o'zgarishda saqlanadi; yangisi ariza yaratilganda saqlanadi."""
    await state.update_data(editing=False)
    data = await state.get_data()
    if not data.get("fresh"):
        await save_profile(chat_id, {k: data.get(k) for k in PROFILE_FIELDS})
    queue = list(data.get("fix_fields") or [])
    if queue:
        await state.update_data(fix_fields=queue[1:])
        await _ask_field(bot, chat_id, state, queue[0])
        return
    if not data.get("fresh"):
        await bot.send_message(chat_id=chat_id, text=PROFILE_SAVED)
    await show_review(bot, chat_id, state)


@router.message(F.text == PROFILE_EDIT_BUTTON, StateFilter(Form.review, Form.confirm))
async def on_edit(message: Message, state: FSMContext):
    await state.set_state(Form.pick_field)
    await message.answer(PROFILE_PICK_FIELD, reply_markup=fields_keyboard())


@router.message(F.text == PROFILE_BACK_BUTTON, StateFilter(Form.pick_field))
async def on_back(message: Message, bot: Bot, state: FSMContext):
    await show_review(bot, message.chat.id, state)


@router.message(F.text.in_(FIELD_BY_LABEL), StateFilter(Form.pick_field))
async def on_field(message: Message, bot: Bot, state: FSMContext):
    await _ask_field(bot, message.chat.id, state, FIELD_BY_LABEL[message.text or ""])


@router.message(F.text == PROFILE_KEEP_BUTTON, StateFilter(Form.review))
async def on_keep(message: Message, bot: Bot, state: FSMContext):
    if not await ai_check_passed(bot, message.chat.id, state):
        return
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
