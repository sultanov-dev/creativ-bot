from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatJoinRequest

from database import get_active_application
from states import Form
from texts import ALREADY_APPLIED, ASK_AGE
from utils.admin import safe_send
from utils.fsm import get_private_state
from utils.get_welcome import welcome_text
from utils.typing import send_typing

router = Router()


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

    # holat javob kelishidan oldin o'rnatilishi kerak
    await private_state.set_state(Form.age)
    await private_state.update_data(
        group_id=request.chat.id, user_id=request.user_chat_id
    )

    await bot.send_message(
        chat_id=request.user_chat_id, text=welcome_text(request.from_user.full_name)
    )
    await send_typing(
        bot=bot,
        chat_id=request.user_chat_id,
        text=ASK_AGE,
        delay=3.0,
    )
