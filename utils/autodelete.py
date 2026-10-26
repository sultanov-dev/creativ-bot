import asyncio
import logging
from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message

from callbacks import VoteCB
from config import AUTO_DELETE_SECONDS

logger = logging.getLogger(__name__)

GROUP_TYPES = {"group", "supergroup"}

# asyncio vazifalarga faqat zaif havola saqlaydi: ular tugamasdan yig'ib olinmasligi uchun
_tasks: set[asyncio.Task] = set()


def _is_vote_message(method: SendMessage) -> bool:
    """Ovoz berish xabari o'chmasligi kerak: u ovoz tugagach utils/voting.py tomonidan o'chiriladi."""
    markup = method.reply_markup
    if not isinstance(markup, InlineKeyboardMarkup):
        return False
    prefix = f"{VoteCB.__prefix__}{VoteCB.__separator__}"
    return any(
        (button.callback_data or "").startswith(prefix)
        for row in markup.inline_keyboard
        for button in row
    )


async def _delete_later(bot: Bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(AUTO_DELETE_SECONDS)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError:
        pass  # xabar allaqachon o'chirilgan yoki o'chirish huquqi yo'q


class AutoDeleteMiddleware(BaseRequestMiddleware):
    """Botning guruhga yozgan xabarlarini AUTO_DELETE_SECONDS dan keyin o'chiradi (guruh to'lib ketmasin).

    Istisno: ovoz berish xabari. Bot qayta ishga tushsa, o'sha paytda kutayotgan o'chirishlar yo'qoladi.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType,
        bot: Bot,
        method: TelegramMethod,
    ) -> Any:
        result = await make_request(bot, method)
        if (
            AUTO_DELETE_SECONDS > 0
            and isinstance(method, SendMessage)
            and isinstance(result, Message)
            and result.chat.type in GROUP_TYPES
            and not _is_vote_message(method)
        ):
            task = asyncio.create_task(_delete_later(bot, result.chat.id, result.message_id))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
        return result
