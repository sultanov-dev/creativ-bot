import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChatMember,
)

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
    BotCommand(command="finish", description="Ovoz berishni darhol tugatish: /finish [ariza_id]"),
]


async def setup_private_commands(bot: Bot) -> None:
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())


async def setup_group_commands(bot: Bot, chat_id: int) -> None:
    """Guruhdagi "/" menyusini faqat shu guruh creator'i uchun o'rnatadi."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        creator = next(a for a in admins if a.status == ChatMemberStatus.CREATOR)
        await bot.set_my_commands(
            CREATOR_COMMANDS,
            scope=BotCommandScopeChatMember(chat_id=chat_id, user_id=creator.user.id),
        )
    except (TelegramBadRequest, TelegramForbiddenError, StopIteration):
        logger.warning("Guruh buyruqlarini o'rnatib bo'lmadi (chat_id=%s)", chat_id)
