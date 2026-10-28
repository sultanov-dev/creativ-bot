import asyncio
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from database import (
    change_status,
    create_application,
    get_active_application,
    mark_admins_notified,
    save_profile,
)
from handlers.profile import ai_check_passed, finish_edit, show_review
from keyboards.action import action_inline
from states import Form
from texts import (
    ALREADY_APPLIED,
    ANKETA_CONFIRM_BUTTON,
    ERROR_GENERIC,
    MODERATION_WARNING,
    ONLY_TEXT,
    PROFILE_USE_BUTTONS,
    SKIP_BUTTON,
    THANKS,
    TOO_LONG,
    WRONG_AGE,
    WRONG_CONTACT,
    WRONG_NAME,
    WRONG_PHONE,
)
from utils.admin import reviewer_ids, safe_send
from utils.form_anketa import PROFILE_FIELDS, format_anketa, full_name_of
from utils.profanity import has_profanity
from utils.num_matcher import extract_number
from utils.questions import ask

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)

# 3 ta javob + ism Telegram'ning 4096 belgilik xabar chegarasiga sig'ishi uchun
MAX_ANSWER_LEN = 800

_finishing: set[int] = set()  # oxirgi javobi hozir ishlanayotgan foydalanuvchilar

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
    user_id = message.chat.id
    if user_id in _finishing:
        return  # ikki marta bosilgan tugma dublikat ariza va admin xabarlarini yaratmasin
    _finishing.add(user_id)
    try:
        # tasdiqlangandan keyin AI butun anketani tekshiradi; muammo bo'lsa, o'sha joylar qayta so'raladi
        if not await ai_check_passed(bot, user_id, state):
            return
        await _finish_application(message, bot, state)
    finally:
        _finishing.discard(user_id)


@router.message(StateFilter(Form.confirm))
async def confirm_use_buttons(message: Message):
    await message.answer(PROFILE_USE_BUTTONS)


async def _finish_application(message: Message, bot: Bot, state: FSMContext) -> None:
    """Tasdiqlangan va AI tekshiruvidan o'tgan anketa: ariza yaratiladi va adminlarga yuboriladi, holat ENG OXIRIDA tozalanadi.

    Bot shu oraliqda to'xtasa, holat va javoblar saqlanib qoladi: "Tasdiqlash" qayta bosilganda shu ariza
    qayta ishlatiladi va adminlarga yetkaziladi (javoblar yo'qolmaydi, ariza adminlarsiz qolib ketmaydi).
    """
    if message.from_user is not None:
        # username so'ralmaydi: avtomatik olinadi va anketada ko'rsatilmaydi
        await state.update_data(username=message.from_user.username)
    data = await state.get_data()
    group_id = data.get("group_id")
    user_id = message.chat.id

    # birinchi anketa saqlanadi: shu foydalanuvchi qayta qo'shilsa, savollar takrorlanmaydi
    await save_profile(user_id, {k: data.get(k) for k in PROFILE_FIELDS})

    if group_id is None:
        logger.warning("group_id topilmadi, user_id=%s", user_id)
        await state.clear()
        await message.answer(ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    admins = await reviewer_ids(bot, group_id)
    if not admins:
        logger.error("Guruh %s uchun anketani ko'rib chiqadigan admin topilmadi", group_id)
        await state.clear()
        await message.answer(ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    full_name = full_name_of(data)
    # guruhga (ovoz berish xabari) ketadigan variant telefonsiz; adminlar va arizachi telefonni ko'radi
    anketa = format_anketa(data)
    private_anketa = format_anketa(data, with_phone=True)

    existing = await get_active_application(user_id, group_id)
    # faqat aynan shu anketadan yaratilgan pending ariza qayta ishlatiladi (oldingi urinish yiqilgan); boshqasi dublikat
    if existing and not (existing["status"] == "pending" and existing["anketa"] == anketa):
        await state.clear()
        await message.answer(ALREADY_APPLIED, reply_markup=ReplyKeyboardRemove())
        return
    # holat hali tozalanmagan bo'lsa, oldingi urinish tugamagan: o'sha ariza qayta ishlatiladi
    app_id = existing["id"] if existing else await create_application(
        user_id,
        group_id,
        full_name,
        anketa,
        tg_username=data.get("username"),
        phone=data.get("phone"),
        admins_notified=False,  # adminlarga yetgach belgilanadi; yetmay qolsa, startda qayta yuboriladi
    )
    if app_id is None:
        await state.clear()
        await message.answer(ALREADY_APPLIED, reply_markup=ReplyKeyboardRemove())
        return

    results = await asyncio.gather(
        *(
            safe_send(
                bot=bot,
                chat_id=admin_id,
                text=private_anketa,
                reply_markup=action_inline(app_id),
            )
            for admin_id in admins
        )
    )

    if not any(results):
        # hech kim ko'ra olmasa, ariza osilib qolmasligi uchun yopamiz: foydalanuvchi qayta urinishi mumkin
        logger.warning(
            "Hech bir admin anketani olmadi (botni start qilmagan bo'lishi mumkin)"
        )
        await change_status(app_id, old="pending", new="failed")
        await state.clear()
        await message.answer(ERROR_GENERIC, reply_markup=ReplyKeyboardRemove())
        return

    await mark_admins_notified(app_id)
    await state.clear()  # eng oxirida: yuqoridagi qadamlar yiqilsa, javoblar yo'qolmaydi
    await message.answer(THANKS, reply_markup=ReplyKeyboardRemove())


@router.message(StateFilter(Form))
async def not_text(message: Message):
    await message.answer(ONLY_TEXT)
