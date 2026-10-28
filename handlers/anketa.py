import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.profile import confirm_and_submit, finish_edit, show_review
from states import Form
from texts import (
    ANKETA_CONFIRM_BUTTON,
    MODERATION_WARNING,
    ONLY_TEXT,
    PROFILE_USE_BUTTONS,
    SKIP_BUTTON,
    TOO_LONG,
    WRONG_AGE,
    WRONG_CONTACT,
    WRONG_NAME,
    WRONG_PHONE,
)
from utils.profanity import has_profanity
from utils.num_matcher import extract_number
from utils.questions import ask

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)

# 3 ta javob + ism Telegram'ning 4096 belgilik xabar chegarasiga sig'ishi uchun
MAX_ANSWER_LEN = 800

PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,25}$", re.ASCII)  # arab-hind kabi Unicode raqamlar o'tmasin


def _is_skip(text: str | None) -> bool:
    return (text or "").strip().lower() in (SKIP_BUTTON.lower(), "/skip")


def _clean_name(text: str | None) -> str | None:
    """Ism va familiya: kamida 2 so'z, 5-80 belgi, kamida bitta harf, raqamsiz, buyruq emas."""
    name = " ".join((text or "").split())
    if not 5 <= len(name) <= 80 or len(name.split()) < 2 or name.startswith("/"):
        return None
    if any(ch.isdigit() for ch in name) or not any(ch.isalpha() for ch in name):
        return None
    return name


def _clean_phone(text: str) -> str | None:
    text = text.strip()
    digits = re.sub(r"\D", "", text, flags=re.ASCII)
    if not PHONE_RE.match(text) or not 7 <= len(digits) <= 15:
        return None
    return ("+" if text.startswith("+") else "") + digits


async def _advance(message: Message, bot: Bot, state: FSMContext, next_state) -> None:
    """Keyingi savolga o'tadi; avval saqlangan anketa tahrirlanayotgan bo'lsa, o'zgarishni saqlab ko'rib chiqishga qaytadi."""
    if (await state.get_data()).get("editing"):
        await finish_edit(bot, message.chat.id, state)
        return
    await state.set_state(next_state)
    await ask(bot, message.chat.id, next_state)


@router.message(F.text, Form.full_name)
async def capture_full_name(message: Message, bot: Bot, state: FSMContext):
    name = _clean_name(message.text)
    if name is None:
        await message.reply(WRONG_NAME)
        return

    if has_profanity(name):
        await message.reply(MODERATION_WARNING)
        return

    await state.update_data(full_name=name)
    await _advance(message, bot, state, Form.phone)


@router.message(F.contact | F.text, Form.phone)
async def capture_phone(message: Message, bot: Bot, state: FSMContext):
    phone = None
    if message.contact:
        # boshqa odamning kontaktini qabul qilmaymiz
        if message.from_user and message.contact.user_id != message.from_user.id:
            await message.reply(WRONG_CONTACT)
            return
        raw = message.contact.phone_number
        phone = raw if raw.startswith("+") else f"+{raw}"
    elif not _is_skip(message.text):
        phone = _clean_phone(message.text or "")
        if phone is None:
            await message.reply(WRONG_PHONE)
            return

    await state.update_data(phone=phone)
    await _advance(message, bot, state, Form.age)


@router.message(F.text, Form.age)
async def capture_age(message: Message, bot: Bot, state: FSMContext):
    age = extract_number(message.text)

    if not age or not (10 <= age <= 100):
        await message.reply(WRONG_AGE)
        return

    await state.update_data(age=age)
    await _advance(message, bot, state, Form.job)


@router.message(F.text, Form.job)
async def capture_job(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    if has_profanity(message.text or ""):
        await message.reply(MODERATION_WARNING)
        return

    await state.update_data(job=message.text)
    await _advance(message, bot, state, Form.about)


@router.message(F.text, Form.about)
async def capture_about(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    if has_profanity(message.text or ""):
        await message.reply(MODERATION_WARNING)
        return

    await state.update_data(about=message.text)
    await _advance(message, bot, state, Form.join_group)


@router.message(F.text, Form.join_group)
async def capture_join_group(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    if has_profanity(message.text or ""):
        await message.reply(MODERATION_WARNING)
        return

    await state.update_data(join_group=message.text)
    if (await state.get_data()).get("editing"):
        await finish_edit(bot, message.chat.id, state)
        return
    # adminlarga yuborishdan oldin: foydalanuvchi anketasini ko'radi va tasdiqlaydi (yoki o'zgartiradi)
    await state.update_data(fresh=True)
    await show_review(bot, message.chat.id, state)


@router.message(F.text == ANKETA_CONFIRM_BUTTON, Form.confirm)
async def on_confirm(message: Message, bot: Bot, state: FSMContext):
    await confirm_and_submit(message, bot, state)


@router.message(StateFilter(Form.confirm))
async def confirm_use_buttons(message: Message):
    await message.answer(PROFILE_USE_BUTTONS)


@router.message(StateFilter(Form))
async def not_text(message: Message):
    await message.answer(ONLY_TEXT)
