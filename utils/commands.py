import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChatMember,
)

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Botni ishga tushirish va anketani davom ettirish"),
]

ADMIN_COMMANDS = [
    BotCommand(command="kick_deleted", description="O'chirilgan akkauntlarni guruhdan chiqarish"),
    BotCommand(command="ban", description="Foydalanuvchini bloklash (xabariga javob bering yoki ID yozing)"),
    BotCommand(command="unban", description="Foydalanuvchini blokdan chiqarish"),
    BotCommand(command="mute", description="Foydalanuvchini jim qilish: /mute [daqiqa]"),
    BotCommand(command="unmute", description="Foydalanuvchini jimlikdan chiqarish"),
    BotCommand(command="stats", description="Guruh a'zolari soni"),
    BotCommand(command="finish", description="Ovoz berishni yakunlash (ovoz xabariga javob bering)"),
]


async def setup_private_commands(bot: Bot) -> None:
    await bot.set_my_commands(PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())


async def setup_group_commands(bot: Bot, chat_id: int) -> None:
    """Guruhdagi "/" menyusini faqat ADMIN_IDS adminlari uchun o'rnatadi."""
    async def one(admin_id: int) -> None:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChatMember(chat_id=chat_id, user_id=admin_id),
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            # admin guruhda emas yoki bot guruhdan chiqarilgan
            logger.warning("Guruh buyruqlarini o'rnatib bo'lmadi (chat_id=%s, admin=%s)", chat_id, admin_id)

    await asyncio.gather(*(one(a) for a in ADMIN_IDS))
