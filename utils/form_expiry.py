from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from config import FORM_TTL_HOURS
from handlers.profile import show_review
from states import Form
from texts import FORM_EXPIRED
from utils.questions import ask

REVIEW_STATES = (Form.review.state, Form.pick_field.state)
FORM_STATES = (
    Form.full_name.state, Form.phone.state, Form.age.state, Form.job.state, Form.about.state,
    Form.join_group.state, *REVIEW_STATES,
)


async def form_expired(state: FSMContext) -> bool:
    """Anketa holati FORM_TTL_HOURS dan ko'proq o'zgarmagan bo'lsa True (0 = hech qachon)."""
    if FORM_TTL_HOURS <= 0:
        return False
    age_of = getattr(state.storage, "state_age", None)
    age = await age_of(state.key) if age_of else None
    return age is not None and age > FORM_TTL_HOURS * 3600


async def restart_expired_form(bot: Bot, chat_id: int, state: FSMContext) -> None:
    """Eskirgan anketa: ogohlantiriladi va savol-javob qaytadan boshlanadi (saqlangan anketa ko'rigi bo'lsa, o'sha qayta ko'rsatiladi)."""
    data = await state.get_data()
    await bot.send_message(chat_id=chat_id, text=FORM_EXPIRED)
    if await state.get_state() in REVIEW_STATES or data.get("editing"):
        data.pop("editing", None)
        await state.set_data(data)
        await show_review(bot, chat_id, state)
        return
    keep = {k: data[k] for k in ("group_id", "user_id", "username") if k in data}
    await state.set_state(Form.full_name)
    await state.set_data(keep)
    await ask(bot, chat_id, Form.full_name, delay=0.3)


class FormExpiryMiddleware(BaseMiddleware):
    """Shaxsiy chatda eskirgan anketaga kelgan xabar javob sifatida qabul qilinmaydi: anketa qaytadan boshlanadi."""

    async def __call__(self, handler: Callable[[Message, dict[str, Any]], Awaitable[Any]], event: Message, data: dict[str, Any]):
        state: FSMContext | None = data.get("state")
        if (
            state is not None
            and event.chat.type == "private"
            and data.get("raw_state") in FORM_STATES
            and await form_expired(state)
        ):
            await restart_expired_form(data["bot"], event.chat.id, state)
            return None
        return await handler(event, data)
