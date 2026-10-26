import logging

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatJoinRequest

from database import get_active_application, get_profile
from handlers.profile import show_review
from states import Form
from texts import ALREADY_APPLIED
from utils.admin import safe_send
from utils.fsm import get_private_state
from utils.get_welcome import welcome_text
from utils.questions import ask

router = Router()
logger = logging.getLogger(__name__)


@router.chat_join_request()
async def join_request(request: ChatJoinRequest, bot: Bot, state: FSMContext):
    # avvalgi ariza hali ko'rib chiqilayotgan bo'lsa, anketani qayta to'ldirtirmaymiz
    if await get_active_application(request.from_user.id, request.chat.id):
        await safe_send(
            bot=bot, chat_id=request.user_chat_id, text=ALREADY_APPLIED
        )
        return

    private_state = get_private_state(
        storage=state.storage, bot=bot, user_id=request.from_user.id
    )

    # avval anketa to'ldirgan bo'lsa: ma'lumotlarni ko'rsatamiz, o'zgartirish yoki shunday qoldirishni so'raymiz
    profile = await get_profile(request.from_user.id)
    if profile:
        await private_state.set_data(
            {**profile, "group_id": request.chat.id, "user_id": request.user_chat_id}
        )
        await private_state.set_state(Form.review)
        await show_review(bot, request.user_chat_id, private_state)
        return

    # holat javob kelishidan oldin o'rnatilishi kerak
    await private_state.set_state(Form.full_name)
    await private_state.set_data(
        {"group_id": request.chat.id, "user_id": request.user_chat_id}
    )

    await bot.send_message(
        chat_id=request.user_chat_id, text=welcome_text()
    )
    await ask(bot, request.user_chat_id, Form.full_name, delay=1.0)
