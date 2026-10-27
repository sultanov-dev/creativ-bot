from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from database import add_member, remove_member

GROUP_TYPES = ("group", "supergroup")

# bir xil (guruh, foydalanuvchi) uchun bazaga qayta-qayta yozmaslik uchun
_seen: set[tuple[int, int]] = set()


_SEEN_MAX = 100_000


async def track(chat_id: int, user_id: int) -> None:
    if (chat_id, user_id) not in _seen:
        if len(_seen) >= _SEEN_MAX:
            # faqat kesh: tozalansa, keyingi yozuvlar bazaga INSERT OR IGNORE bilan qayta tushadi
            _seen.clear()
        await add_member(chat_id, user_id)
        _seen.add((chat_id, user_id))


async def untrack(chat_id: int, user_id: int) -> None:
    _seen.discard((chat_id, user_id))
    await remove_member(chat_id, user_id)


class TrackMembersMiddleware(BaseMiddleware):
    """Guruhda ko'ringan a'zolarni eslab qoladi (Bot API a'zolar ro'yxatini bermaydi)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type in GROUP_TYPES:
            chat_id = event.chat.id
            if event.from_user and not event.from_user.is_bot:
                await track(chat_id, event.from_user.id)
            for user in event.new_chat_members or []:
                if not user.is_bot:
                    await track(chat_id, user.id)
            if event.left_chat_member and not event.left_chat_member.is_bot:
                await untrack(chat_id, event.left_chat_member.id)

        return await handler(event, data)
