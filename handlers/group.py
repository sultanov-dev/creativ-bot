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

from database import get_members
from utils.admin import get_user_status
from utils.commands import setup_group_commands
from utils.members import track, untrack

# Telegram o'chirilgan akkauntlarni shu ism bilan qaytaradi
DELETED_NAME = "Deleted Account"

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


# avval arzon tekshiruv (bizning buyruqmi?), keyin API chaqiruvli creator_only: har bir "/..." xabar uchun so'rov ketmasin
router.message.filter(
    Command("kick_deleted", "ban", "unban", "mute", "unmute", "stats")
)
router.message.filter(creator_only)

# mute muddati chegarasi (1 yil): timedelta/Telegram'da haddan katta son xatoga olib kelmasin
MAX_MUTE_MINUTES = 366 * 24 * 60


def _is_number(text: str) -> bool:
    # str.isdigit() "²" kabi belgilarni ham qabul qiladi, int() esa ularda xato beradi
    return text.isascii() and text.isdigit()


def _target_id(message: Message, command: CommandObject) -> int | None:
    """Reply qilingan foydalanuvchi yoki buyruq argumentidagi ID."""
    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user.id
    if command.args and _is_number(command.args.split()[0].lstrip("-")):
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


@router.chat_member(F.chat.type.in_({"group", "supergroup"}))
async def member_changed(event: ChatMemberUpdated):
    """A'zolar ro'yxatini yangilab boradi (qo'shilganda/chiqqanda)."""
    member = event.new_chat_member
    if member.user.is_bot:
        return

    is_in = member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    ) or (member.status == ChatMemberStatus.RESTRICTED and member.is_member)

    if is_in:
        await track(event.chat.id, member.user.id)
    else:
        await untrack(event.chat.id, member.user.id)


async def _get_member(bot: Bot, chat_id: int, user_id: int):
    for attempt in range(2):
        try:
            return await bot.get_chat_member(chat_id, user_id)
        except TelegramRetryAfter as e:
            if attempt == 1:
                raise
            await asyncio.sleep(e.retry_after)


@router.message(Command("kick_deleted"))
async def kick_deleted(message: Message, bot: Bot):
    chat_id = message.chat.id
    members = await get_members(chat_id)
    status_msg = await message.reply(
        f"🔎 Bot kuzatgan {len(members)} ta a'zo tekshirilmoqda..."
    )

    kicked = failed = 0
    for user_id in members:
        try:
            member = await _get_member(bot, chat_id, user_id)
        except TelegramBadRequest:
            # foydalanuvchi topilmadi (guruhda yo'q): ro'yxatdan olib tashlaymiz
            await untrack(chat_id, user_id)
            continue
        except (TelegramForbiddenError, TelegramRetryAfter):
            logger.warning("Tekshirib bo'lmadi: %s", user_id)
            failed += 1
            continue

        if member is None or member.status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
        ):
            await untrack(chat_id, user_id)
        elif member.user.first_name == DELETED_NAME:
            try:
                await _remove(bot, chat_id, user_id, ban=False)
                await untrack(chat_id, user_id)
                kicked += 1
            except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
                logger.warning("Chiqarib bo'lmadi: %s", user_id)
                failed += 1
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"🧹 Tekshirildi: {len(members)}, o'chirilgan akkaunt chiqarildi: {kicked}, "
        f"xato: {failed}.\n"
        "Eslatma: bot faqat o'zi ko'rgan (yozgan yoki qo'shilgan) a'zolarni biladi."
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

    minutes = int(command.args) if command.args and _is_number(command.args) else 60
    minutes = min(max(minutes, 1), MAX_MUTE_MINUTES)
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
