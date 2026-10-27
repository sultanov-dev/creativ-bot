import asyncio
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message, TelegramObject

from callbacks import VoteCB
from config import AUTO_DELETE_SECONDS
from database import add_pending_delete, get_pending_deletes, remove_pending_delete

logger = logging.getLogger(__name__)

GROUP_TYPES = {"group", "supergroup"}

# asyncio vazifalarga faqat zaif havola saqlaydi: ular tugamasdan yig'ib olinmasligi uchun
_tasks: set[asyncio.Task] = set()


# True bo'lsa, shu kontekstda yuborilgan xabar o'chirilmaydi (masalan, AI javobi)
_keep = ContextVar("autodelete_keep", default=False)


@contextmanager
def keep_messages():
    """with bloki ichida yuborilgan guruh xabarlari avto-o'chirilmaydi."""
    token = _keep.set(True)
    try:
        yield
    finally:
        _keep.reset(token)


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


async def _delete_at(bot: Bot, chat_id: int, message_id: int, when: float) -> None:
    await asyncio.sleep(max(0.0, when - time.time()))
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramAPIError as e:
        # xabar allaqachon o'chirilgan yoki botda "xabarlarni o'chirish" huquqi yo'q
        logger.warning("Xabarni o'chirib bo'lmadi (chat=%s, message=%s): %s", chat_id, message_id, e)
    # bot to'xtatilganda (CancelledError) qator qoladi: keyingi ishga tushishda davom etadi
    await remove_pending_delete(chat_id, message_id)


def _start(bot: Bot, chat_id: int, message_id: int, when: float) -> None:
    task = asyncio.create_task(_delete_at(bot, chat_id, message_id, when))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def schedule_delete(bot: Bot, chat_id: int, message_id: int, delay: int | None = None) -> None:
    """Xabarni `delay` soniyadan keyin o'chirishga qo'yadi; delay berilmasa AUTO_DELETE_SECONDS (0 bo'lsa hech narsa qilmaydi).

    Navbat bazada saqlanadi: bot qayta ishga tushsa, restore_pending_deletes() davom ettiradi.
    """
    seconds = AUTO_DELETE_SECONDS if delay is None else delay
    if seconds <= 0:
        return
    when = time.time() + seconds
    await add_pending_delete(chat_id, message_id, int(when))
    _start(bot, chat_id, message_id, when)


async def restore_pending_deletes(bot: Bot) -> None:
    """Bot ishga tushganda: o'tgan o'chirishlar darhol bajariladi, qolganlari o'z vaqtida."""
    rows = await get_pending_deletes()
    for row in rows:
        _start(bot, row["chat_id"], row["message_id"], row["delete_at"])
    if rows:
        logger.info("Kutayotgan %s ta xabar o'chirish tiklandi", len(rows))


class CommandCleanupMiddleware(BaseMiddleware):
    """Admin guruhga yozgan va bot ishlagan buyruq xabarini ham (/finish, /ban...) o'chiradi: chat to'lib qolmasin.

    Faqat handler topilgan xabarlarga ishlaydi (router.message.middleware): begona buyruqlarga tegmaydi.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        finally:
            if isinstance(event, Message) and event.chat.type in GROUP_TYPES:
                await schedule_delete(data["bot"], event.chat.id, event.message_id)


class AutoDeleteMiddleware(BaseRequestMiddleware):
    """Botning guruhga yozgan xabarlarini AUTO_DELETE_SECONDS dan keyin o'chiradi (guruh to'lib ketmasin).

    Istisno: ovoz berish xabari va `keep_messages()` ichida yuborilganlar (AI javoblari). Bot qayta ishga tushsa, o'sha paytda kutayotgan o'chirishlar yo'qoladi.
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
            and not _keep.get()
            and not _is_vote_message(method)
        ):
            await schedule_delete(bot, result.chat.id, result.message_id)
        return result
