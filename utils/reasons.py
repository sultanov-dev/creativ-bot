from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from utils.admin import safe_send


async def _group_admin_ids(bot: Bot, group_id: int) -> list[int]:
    try:
        admins = await bot.get_chat_administrators(chat_id=group_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return []
    return [a.user.id for a in admins if not a.user.is_bot]


async def send_to_admins(bot: Bot, group_id: int, text: str) -> None:
    for admin_id in await _group_admin_ids(bot, group_id):
        await safe_send(bot=bot, chat_id=admin_id, text=text)
