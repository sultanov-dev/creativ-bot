from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatJoinRequest

from states import Form
from texts import ASK_AGE
from utils.fsm import get_private_state
from utils.get_welcome import welcome_text
from utils.typing import send_typing

router = Router()


@router.chat_join_request()
async def join_request(request: ChatJoinRequest, bot: Bot, state: FSMContext):
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
