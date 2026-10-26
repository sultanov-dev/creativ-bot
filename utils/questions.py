from aiogram import Bot
from aiogram.fsm.state import State
from aiogram.types import ReplyKeyboardRemove

from keyboards.skip import phone_keyboard, skip_keyboard
from states import Form
from texts import (
    ASK_ABOUT,
    ASK_AGE,
    ASK_FULL_NAME,
    ASK_JOB,
    ASK_PHONE,
    ASK_REASON,
    ASK_USERNAME,
)
from utils.typing import send_typing

# holat -> (savol matni, klaviatura yasovchi); ixtiyoriy savollarda "o'tkazib yuborish" tugmasi bor
QUESTIONS = {
    Form.full_name.state: (ASK_FULL_NAME, None),
    Form.username.state: (ASK_USERNAME, skip_keyboard),
    Form.phone.state: (ASK_PHONE, phone_keyboard),
    Form.age.state: (ASK_AGE, None),
    Form.job.state: (ASK_JOB, None),
    Form.about.state: (ASK_ABOUT, None),
    Form.join_group.state: (ASK_REASON, None),
}


def question_for(state: State | str) -> tuple[str, object] | None:
    """Savol matni va reply_markup; ixtiyoriy bo'lmagan savolda eski klaviatura olib tashlanadi."""
    name = state.state if isinstance(state, State) else state
    item = QUESTIONS.get(name)
    if item is None:
        return None
    text, make_markup = item
    return text, (make_markup() if make_markup else ReplyKeyboardRemove())


async def ask(bot: Bot, chat_id: int, state: State | str, delay: float = 2.0) -> None:
    text, markup = question_for(state)  # type: ignore[misc]
    await send_typing(bot=bot, chat_id=chat_id, text=text, delay=delay, reply_markup=markup)
