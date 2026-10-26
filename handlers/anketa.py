import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import ADMIN_IDS
from database import change_status, create_application, get_active_application, save_profile
from handlers.profile import finish_edit
from keyboards.action import action_inline
from states import Form
from texts import (
    ALREADY_APPLIED,
    ERROR_GENERIC,
    ONLY_TEXT,
    SKIP_BUTTON,
    THANKS,
    TOO_LONG,
    WRONG_AGE,
    WRONG_CONTACT,
    WRONG_NAME,
    WRONG_PHONE,
    WRONG_USERNAME,
)
from utils.admin import safe_send
from utils.form_anketa import PROFILE_FIELDS, format_anketa, full_name_of
from utils.num_matcher import extract_number
from utils.questions import ask

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)

# 3 ta javob + ism Telegram'ning 4096 belgilik xabar chegarasiga sig'ishi uchun
MAX_ANSWER_LEN = 800

USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
PHONE_RE = re.compile(r"^\+?[\d\s\-()]{7,25}$")


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
    digits = re.sub(r"\D", "", text)
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

    await state.update_data(full_name=name)
    await _advance(message, bot, state, Form.username)


@router.message(F.text, Form.username)
async def capture_username(message: Message, bot: Bot, state: FSMContext):
    if _is_skip(message.text):
        username = None
    else:
        match = USERNAME_RE.match((message.text or "").strip())
        if match is None:
            await message.reply(WRONG_USERNAME)
            return
        username = match.group(1)

    await state.update_data(username=username)
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

    await state.update_data(job=message.text)
    await _advance(message, bot, state, Form.about)


@router.message(F.text, Form.about)
async def capture_about(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    await state.update_data(about=message.text)
    await _advance(message, bot, state, Form.join_group)


@router.message(F.text, Form.join_group)
async def capture_join_group(message: Message, bot: Bot, state: FSMContext):
    if len(message.text or "") > MAX_ANSWER_LEN:
        await message.reply(TOO_LONG)
        return

    await state.update_data(join_group=message.text)
    data = await state.get_data()
    if data.get("editing"):
        await finish_edit(bot, message.chat.id, state)
        return
    group_id = data.get("group_id")
    user_id = message.chat.id
    await state.clear()

    # birinchi anketa saqlanadi: shu foydalanuvchi qayta qo'shilsa, savollar takrorlanmaydi
    await save_profile(user_id, {k: data.get(k) for k in PROFILE_FIELDS})

    full_name = full_name_of(data)
    # guruhga (ovoz berish xabari) ketadigan variant telefonsiz; adminlar va arizachi telefonni ko'radi
    anketa = format_anketa(data)
    private_anketa = format_anketa(data, with_phone=True)

    if group_id is None:
        logger.warning("group_id topilmadi, user_id=%s", user_id)
        await message.answer(ERROR_GENERIC)
        return

    if not ADMIN_IDS:
        logger.error("ADMIN_IDS bo'sh: anketani ko'rib chiqadigan admin yo'q")
        await message.answer(ERROR_GENERIC)
        return

    if await get_active_application(user_id, group_id):
        await message.answer(ALREADY_APPLIED)
        return

    app_id = await create_application(
        user_id,
        group_id,
        full_name,
        anketa,
        tg_username=data.get("username"),
        phone=data.get("phone"),
    )
    if app_id is None:
        await message.answer(ALREADY_APPLIED)
        return

    results = await asyncio.gather(
        *(
            safe_send(
                bot=bot,
                chat_id=admin_id,
                text=private_anketa,
                reply_markup=action_inline(app_id),
            )
            for admin_id in ADMIN_IDS
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

    await message.answer(private_anketa)
    await message.answer(THANKS)


@router.message(StateFilter(Form))
async def not_text(message: Message):
    await message.answer(ONLY_TEXT)
