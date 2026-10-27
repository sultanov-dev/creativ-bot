import asyncio
import logging
import re
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

from database import (
    end_voting_now,
    get_application_by_vote_message,
    get_members,
    mark_removed,
)
from utils.admin import is_admin
from utils.autodelete import CommandCleanupMiddleware, schedule_delete
from utils.commands import setup_group_commands
from utils.members import track, untrack
from utils.voting import finalize_due_votings

# Telegram o'chirilgan akkauntlarni shu ism bilan qaytaradi
DELETED_NAME = "Deleted Account"

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = logging.getLogger(__name__)


async def admin_only(message: Message) -> bool:
    """Buyruqlarni faqat bot adminlari (ADMIN_IDS) bajara oladi; boshqalarga bot javob bermaydi."""
    return message.from_user is not None and is_admin(message.from_user.id)


def _is_protected(user_id: int) -> bool:
    """Bot adminlari (ADMIN_IDS) bloklanmasligi/jim qilinmasligi kerak; Telegram'dagi guruh adminligi hisobga olinmaydi."""
    return is_admin(user_id)


COMMANDS = ("kick_deleted", "ban", "unban", "mute", "unmute", "stats", "finish")
router.message.filter(Command(*COMMANDS))
router.message.filter(admin_only)
# adminning buyruq xabari ham (bot javobi kabi) AUTO_DELETE_SECONDS dan keyin o'chadi
router.message.middleware(CommandCleanupMiddleware())

# admin bo'lmaganlarning "/..." xabarlari (bot buyrug'i bo'lsin yoki oddiy matn): bot javob bermaydi, e'tibor bermaydi
# (foydalanuvchilar qanday buyruqlar borligini bilmasligi kerak), xabar esa STRANGER_DELETE_SECONDS dan keyin o'chadi.
# Boshqa botga yo'naltirilgan buyruqlarga (/cmd@boshqa_bot) tegilmaydi.
STRANGER_DELETE_SECONDS = 15  # ataylab .env dan olinmaydi
strangers = Router()
strangers.message.filter(F.chat.type.in_({"group", "supergroup"}))


async def stranger_slash(message: Message, bot: Bot) -> bool:
    user = message.from_user
    if user is None or user.is_bot or is_admin(user.id):
        return False
    text = message.text or ""
    if not text.startswith("/"):
        return False
    _, _, mention = text.split(maxsplit=1)[0].partition("@")
    return not mention or mention.lower() == (await bot.me()).username.lower()  # type: ignore[union-attr]


@strangers.message(stranger_slash)
async def stranger_command(message: Message, bot: Bot):
    await schedule_delete(bot, message.chat.id, message.message_id, delay=STRANGER_DELETE_SECONDS)


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
    token = command.args.split()[0] if command.args else ""
    # faqat ASCII raqam, ixtiyoriy bitta minus ('--5' va '²' int() da xato beradi)
    if re.fullmatch(r"-?[0-9]+", token):
        return int(token)
    return None


async def _remove(bot: Bot, chat_id: int, user_id: int, *, ban: bool) -> None:
    """ban=False bo'lsa foydalanuvchi chiqariladi, lekin qayta qo'shilishi mumkin."""
    for attempt in range(2):
        try:
            await bot.ban_chat_member(chat_id, user_id)
            if not ban:
                await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            # chiqarilgan/bloklangan foydalanuvchi qayta qo'shilsa, yana admin ko'rigidan o'tadi
            await mark_removed(user_id, chat_id)
            return
        except TelegramRetryAfter as e:
            if attempt == 1:
                raise
            await asyncio.sleep(e.retry_after)


@router.my_chat_member(F.chat.type.in_({"group", "supergroup"}))
async def bot_added(event: ChatMemberUpdated, bot: Bot):
    """Bot guruhga qo'shilganda yoki admin qilinganda admin menyusini o'rnatadi."""
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

    if member.status == ChatMemberStatus.KICKED:
        # Telegram'dan qo'lda bloklangan holat ham (bot orqali emas)
        await mark_removed(member.user.id, event.chat.id)

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
        f"🔎 Bot kuzatgan {len(members)} ta a'zo tekshirilmoqda…"
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
        await message.reply("Foydalanuvchi xabariga javob bering yoki ID yozing: /ban &lt;id&gt;")
        return
    if _is_protected(user_id):
        await message.reply("Kechirasiz, adminni bloklab bo'lmaydi.")
        return

    try:
        await _remove(bot, message.chat.id, user_id, ban=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Kechirasiz, bloklab bo'lmadi. Botda yetarli huquq borligini tekshiring.")
        return
    await message.reply(f"🚫 <code>{user_id}</code> bloklandi")


@router.message(Command("unban"))
async def unban(message: Message, command: CommandObject, bot: Bot):
    user_id = _target_id(message, command)
    if user_id is None:
        await message.reply("Foydalanuvchi xabariga javob bering yoki ID yozing: /unban &lt;id&gt;")
        return
    try:
        await bot.unban_chat_member(message.chat.id, user_id, only_if_banned=True)
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Kechirasiz, blokdan chiqarib bo'lmadi.")
        return
    await message.reply(f"✅ <code>{user_id}</code> blokdan chiqarildi")


@router.message(Command("mute"))
async def mute(message: Message, command: CommandObject, bot: Bot):
    reply = message.reply_to_message
    if reply is None or reply.from_user is None:
        await message.reply("Foydalanuvchi xabariga javob bering: /mute [daqiqa]")
        return

    user_id = reply.from_user.id
    if _is_protected(user_id):
        await message.reply("Kechirasiz, adminni jim qilib bo'lmaydi.")
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
        await message.reply("Kechirasiz, jim qilib bo'lmadi. Botda yetarli huquq borligini tekshiring.")
        return
    await message.reply(
        f"🔇 {escape(reply.from_user.full_name)} {minutes} daqiqaga jim qilindi"
    )


@router.message(Command("unmute"))
async def unmute(message: Message, bot: Bot):
    reply = message.reply_to_message
    if reply is None or reply.from_user is None:
        await message.reply("Foydalanuvchi xabariga javob bering: /unmute")
        return

    chat = await bot.get_chat(message.chat.id)
    permissions = chat.permissions or ChatPermissions(can_send_messages=True)
    try:
        await bot.restrict_chat_member(
            message.chat.id, reply.from_user.id, permissions=permissions
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.reply("Kechirasiz, jimlikdan chiqarib bo'lmadi.")
        return
    await message.reply(f"🔊 {escape(reply.from_user.full_name)} jimlikdan chiqarildi")


@router.message(Command("stats"))
async def stats(message: Message, bot: Bot):
    count = await bot.get_chat_member_count(message.chat.id)
    await message.reply(f"👥 Guruhda a'zolar soni: <b>{count}</b>")


@router.message(Command("finish"))
async def finish(message: Message, bot: Bot):
    """Reply qilingan ovoz berish xabaridagi ovozni darhol tugatadi; natija ovozlar bo'yicha chiqadi (60% qoidasi; ikkala tomon yetmasa adminlarga hisobot ketadi). Guruhga faqat qisqa javob yoziladi.

    Reply bo'lmasa hech narsa tugatilmaydi: guruhdagi boshqa faol ovozlar tegilmaydi.
    """
    reply = message.reply_to_message
    if reply is None:
        await message.reply(
            "Yakunlamoqchi bo'lgan ovoz berish xabariga javob bergan holda /finish yozing. "
            "Faqat o'sha ovoz yakunlanadi."
        )
        return

    app = await get_application_by_vote_message(message.chat.id, reply.message_id)
    if app is None:
        await message.reply("Bu ovoz berish xabari emas. Iltimos, ovoz berish xabariga javob bering.")
        return
    if app["status"] != "voting":
        await message.reply("Bu ariza bo'yicha ovoz berish allaqachon yakunlangan.")
        return

    await end_voting_now(message.chat.id, app["id"])
    await finalize_due_votings(bot)

    # natija adminlarga alohida xabar bilan yuborilmaydi (kerak bo'lsa, qaror hisoboti o'zi keladi);
    # guruhdagi qisqa javob AUTO_DELETE_SECONDS dan keyin o'chadi
    await message.reply("🏁 Ovoz berish yakunlandi.")
