import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChatMember,
)

from config import GROUP_ID

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish"),
]

CREATOR_COMMANDS = [
    BotCommand(command="kick_deleted", description="O'chirilgan akkauntlarni guruhdan chiqarish"),
    BotCommand(command="ban", description="Foydalanuvchini ban qilish (reply yoki ID)"),
    BotCommand(command="unban", description="Foydalanuvchini bandan chiqarish"),
    BotCommand(command="mute", description="Foydalanuvchini jim qilish: /mute [daqiqa]"),
    BotCommand(command="unmute", description="Foydalanuvchini jimlikdan chiqarish"),
    BotCommand(command="stats", description="Guruh a'zolari soni"),
]


async def setup_commands(bot: Bot) -> None:
    """"/" bosilganda chiqadigan buyruqlar ro'yxati: lichkada /start, guruhda faqat creator uchun moderatsiya."""
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())

    if not GROUP_ID:
        return

    try:
        admins = await bot.get_chat_administrators(GROUP_ID)
        creator = next(a for a in admins if a.status == ChatMemberStatus.CREATOR)
        await bot.set_my_commands(
            CREATOR_COMMANDS,
            scope=BotCommandScopeChatMember(chat_id=GROUP_ID, user_id=creator.user.id),
        )
    except (TelegramBadRequest, TelegramForbiddenError, StopIteration):
        logger.warning("Guruh buyruqlarini o'rnatib bo'lmadi (GROUP_ID=%s)", GROUP_ID)
