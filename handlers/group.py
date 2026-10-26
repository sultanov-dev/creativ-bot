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

from database import (
    count_votes,
    end_voting_now,
    get_application,
    get_application_by_vote_message,
    get_members,
)
from utils.admin import get_user_status, is_admin, safe_send
from utils.autodelete import CommandCleanupMiddleware
from utils.commands import setup_group_commands
from utils.members import track, untrack
from utils.voting import finalize_due_votings

# Telegram o'chirilgan akkauntlarni shu ism bilan qaytaradi
DELETED_NAME = "Deleted Account"

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = logging.getLogger(__name__)

PRIVILEGED = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def admin_only(message: Message) -> bool:
    """Buyruqlarni faqat bot adminlari (ADMIN_IDS) bajara oladi; boshqalarga bot javob bermaydi."""
    return message.from_user is not None and is_admin(message.from_user.id)


async def _is_protected(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Bot admini yoki guruh admini bloklanmasligi/jim qilinmasligi kerak."""
    return is_admin(user_id) or await get_user_status(bot, chat_id, user_id) in PRIVILEGED


router.message.filter(
    Command("kick_deleted", "ban", "unban", "mute", "unmute", "stats", "finish")
)
router.message.filter(admin_only)
# adminning buyruq xabari ham (bot javobi kabi) AUTO_DELETE_SECONDS dan keyin o'chadi
router.message.middleware(CommandCleanupMiddleware())

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
    if await _is_protected(bot, message.chat.id, user_id):
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
    if await _is_protected(bot, message.chat.id, user_id):
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


FINISH_RESULTS = {
    "accepted": "✅ qabul qilindi",
    "creator_review": "🔎 qaror adminlarga yuborildi (ikkala tomon ham kerakli foizga yetmadi)",
    "rejected": "❌ rad etildi",
    "expired": "⌛ hech kim ovoz bermadi, ariza yopildi",
    "voting": "⏳ vaqtincha xatolik, birozdan keyin o'zi yakunlanadi",
}


@router.message(Command("finish"))
async def finish(message: Message, bot: Bot):
    """Reply qilingan ovoz berish xabaridagi ovozni darhol tugatadi; natija ovozlar bo'yicha chiqadi (60% qoidasi; ikkala tomon yetmasa adminlarga hisobot ketadi), buyruq bergan adminga lichkada qisqa natija yuboriladi.

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

    app = await get_application(app["id"]) or app
    yes, no = await count_votes(app["id"])
    report = (
        "🏁 <b>Ovoz berish yakunlandi</b>\n\n"
        f"№{app['id']} <b>{escape(app['full_name'])}</b>: {yes} 👍 / {no} 👎, "
        f"{FINISH_RESULTS.get(app['status'], app['status'])}"
    )

    delivered = await safe_send(bot=bot, chat_id=message.from_user.id, text=report)
    if delivered:
        await message.reply("🏁 Ovoz berish yakunlandi, hisobot shaxsiy xabaringizga yuborildi.")
    else:
        await message.reply(
            "🏁 Ovoz berish yakunlandi, lekin hisobotni shaxsiy xabar sifatida yubora olmadim. "
            "Botning shaxsiy chatida /start bosing."
        )
