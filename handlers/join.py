import logging

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatJoinRequest

from database import (
    change_status,
    create_application,
    get_active_application,
    get_application,
    get_profile,
)
from states import Form
from texts import ALREADY_APPLIED, ERROR_GENERIC, REPEAT_APPLICATION_SENT
from utils.admin import safe_send
from utils.applications import open_voting
from utils.form_anketa import format_anketa, full_name_of
from utils.fsm import get_private_state
from utils.get_welcome import welcome_text
from utils.questions import ask

router = Router()
logger = logging.getLogger(__name__)


async def _apply_from_profile(request: ChatJoinRequest, bot: Bot, profile: dict) -> None:
    """Avval anketa to'ldirgan foydalanuvchi: savollarsiz, saqlangan ma'lumot bilan to'g'ridan-to'g'ri ovozga qo'yiladi."""
    user_id = request.from_user.id
    app_id = await create_application(
        user_id,
        request.chat.id,
        full_name_of(profile),
        format_anketa(profile),
        first_name=profile.get("first_name"),
        last_name=profile.get("last_name"),
        tg_username=profile.get("username"),
        phone=profile.get("phone"),
    )
    if app_id is None:
        await safe_send(bot=bot, chat_id=request.user_chat_id, text=ALREADY_APPLIED)
        return

    app = await get_application(app_id)
    if app is None or not await open_voting(bot, app):
        # ovoz xabari guruhga ketmadi: ariza osilib qolmasin, foydalanuvchi qayta urinishi mumkin
        logger.warning("Saqlangan anketa bilan ovoz berishni boshlab bo'lmadi, ariza %s", app_id)
        await change_status(app_id, old="pending", new="failed")
        await safe_send(bot=bot, chat_id=request.user_chat_id, text=ERROR_GENERIC)
        return

    await safe_send(bot=bot, chat_id=request.user_chat_id, text=REPEAT_APPLICATION_SENT)


@router.chat_join_request()
async def join_request(request: ChatJoinRequest, bot: Bot, state: FSMContext):
    # avvalgi ariza hali ko'rib chiqilayotgan bo'lsa, anketani qayta to'ldirtirmaymiz
    if await get_active_application(request.from_user.id, request.chat.id):
        await safe_send(
            bot=bot, chat_id=request.user_chat_id, text=ALREADY_APPLIED
        )
        return

    # avval anketa to'ldirgan bo'lsa, qayta so'ramaymiz
    profile = await get_profile(request.from_user.id)
    if profile:
        await _apply_from_profile(request, bot, profile)
        return

    private_state = get_private_state(
        storage=state.storage, bot=bot, user_id=request.from_user.id
    )

    # holat javob kelishidan oldin o'rnatilishi kerak
    await private_state.set_state(Form.full_name)
    await private_state.update_data(
        group_id=request.chat.id, user_id=request.user_chat_id
    )

    await bot.send_message(
        chat_id=request.user_chat_id, text=welcome_text()
    )
    await ask(bot, request.user_chat_id, Form.full_name, delay=1.0)
