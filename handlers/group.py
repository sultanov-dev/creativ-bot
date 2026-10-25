import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatMemberUpdated, ChatPermissions, Message

from utils import userbot
from utils.admin import get_user_status
from utils.commands import setup_group_commands

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = logging.getLogger(__name__)

PRIVILEGED = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def creator_only(message: Message, bot: Bot) -> bool:
    """Buyruqlarni faqat guruh creator'i bajara oladi; boshqalarga bot javob bermaydi."""
    if message.from_user is None:
        return False
    status = await get_user_status(bot, message.chat.id, message.from_user.id)
    return status == ChatMemberStatus.CREATOR


router.message.filter(creator_only)


def _target_id(message: Message, command: CommandObject) -> int | None:
    """Reply qilingan foydalanuvchi yoki buyruq argumentidagi ID."""
    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user.id
    if command.args and command.args.split()[0].lstrip("-").isdigit():
        return int(command.args.split()[0])
    return None


async def _remove(bot: Bot, chat_id: int, user_id: int, *, ban: bool) -> None:
    """ban=False bo'lsa foydalanuvchi chiqariladi, lekin qayta qo'shilishi mumkin."""
    for attempt in range(2):
        try:
            await bot.ban_chat_member(chat_id, user_id)
            if not ban:
                await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            return
        except TelegramRetryAfter as e:
            if attempt == 1:
                raise
            await asyncio.sleep(e.retry_after)


@router.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
async def bot_added(event: ChatMemberUpdated, bot: Bot):
    """Bot guruhga qo'shilganda yoki admin qilinganda creator menyusini o'rnatadi."""
    if event.new_chat_member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    ):
        await setup_group_commands(bot, event.chat.id)


@router.message(Command("kick_deleted"))
async def kick_deleted(message: Message, bot: Bot):
    if not userbot.is_ready():
        await message.reply(
            "Userbot ulanmagan. `.env` da API_ID/API_HASH ni to'ldirib, "
            "`python userbot_login.py` ni ishga tushiring."
        )
        return

    status_msg = await message.reply("🔎 O'chirilgan akkauntlar qidirilmoqda...")
    deleted = await userbot.list_deleted(message.chat.id)

    kicked = failed = 0
    for user_id in deleted:
        try:
            await _remove(bot, message.chat.id, user_id, ban=False)
            kicked += 1
        except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
            logger.warning("Chiqarib bo'lmadi: %s", user_id)
            failed += 1
        await asyncio.sleep(0.1)

    await status_msg.edit_text(
        f"🧹 O'chirilgan akkauntlar: topildi {len(deleted)}, "
        f"chiqarildi {kicked}, xato {failed}."
    )


@router.message(Command("ban"))
async def ban(message: Message, command: CommandObject, bot: Bot):
    user_id = _target_id(message, command)
    if user_id is None:
        await message.reply("Foydalanuvchiga reply qiling yoki ID yozing: /ban &lt;id&gt;")
        return
    if await get_user_status(bot, message.chat.id, user_id) in PRIVILEGED:
        await message.reply("Adminni ban qilib bo'lmaydi")
        return

    try:
        await _remove(bot, message.chat.id, user_id, ban=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Ban qilib bo'lmadi (botda huquq yo'qmi?)")
        return
    await message.reply(f"🚫 <code>{user_id}</code> ban qilindi")


@router.message(Command("unban"))
async def unban(message: Message, command: CommandObject, bot: Bot):
    user_id = _target_id(message, command)
    if user_id is None:
        await message.reply("Foydalanuvchiga reply qiling yoki ID yozing: /unban &lt;id&gt;")
        return
    try:
        await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Bandan chiqarib bo'lmadi")
        return
    await message.reply(f"✅ <code>{user_id}</code> bandan chiqarildi")


@router.message(Command("mute"))
async def mute(message: Message, command: CommandObject, bot: Bot):
    reply = message.reply_to_message
    if reply is None or reply.from_user is None:
        await message.reply("Foydalanuvchi xabariga reply qiling: /mute [daqiqa]")
        return

    user_id = reply.from_user.id
    if await get_user_status(bot, message.chat.id, user_id) in PRIVILEGED:
        await message.reply("Adminni mute qilib bo'lmaydi")
        return

    minutes = int(command.args) if command.args and command.args.isdigit() else 60
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Mute qilib bo'lmadi (botda huquq yo'qmi?)")
        return
    await message.reply(
        f"🔇 {escape(reply.from_user.full_name)} {minutes} daqiqaga mute qilindi"
    )


@router.message(Command("unmute"))
async def unmute(message: Message, bot: Bot):
    reply = message.reply_to_message
    if reply is None or reply.from_user is None:
        await message.reply("Foydalanuvchi xabariga reply qiling: /unmute")
        return

    chat = await bot.get_chat(message.chat.id)
    permissions = chat.permissions or ChatPermissions(can_send_messages=True)
    try:
        await bot.restrict_chat_member(
            message.chat.id, reply.from_user.id, permissions=permissions
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Mute'ni olib bo'lmadi")
        return
    await message.reply(f"🔊 {escape(reply.from_user.full_name)} mute'dan chiqarildi")


@router.message(Command("stats"))
async def stats(message: Message, bot: Bot):
    count = await bot.get_chat_member_count(message.chat.id)
    await message.reply(f"👥 Guruhda a'zolar soni: <b>{count}</b>")
