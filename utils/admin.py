import asyncio
import logging
from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

GROUP_ADMIN_STATUSES = (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def get_user_status(bot: Bot, chat_id: int, user_id: int):
    try:
        members = await bot.get_chat_member(chat_id, user_id)
        return members.status
    except (TelegramBadRequest, TelegramForbiddenError):
        return None


async def is_group_member(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Hozir guruhda turgan foydalanuvchimi (chiqib ketgan 'restricted' a'zo hisoblanmaydi)."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return False
    if member.status == ChatMemberStatus.RESTRICTED:
        return bool(member.is_member)
    return member.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    )


def is_admin(user_id: int) -> bool:
    """Bot admini (guruh buyruqlarini bajaradi): faqat ADMIN_IDS ro'yxati (.env) hisoblanadi."""
    return user_id in ADMIN_IDS


async def is_reviewer(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Anketa, ovoz va yakuniy qaror admini: guruhning Telegram admini (egasi ham) yoki ADMIN_IDS dagi bot admini.

    Guruh buyruqlari bundan farqli: ularni faqat ADMIN_IDS (is_admin) bajaradi.
    """
    return is_admin(user_id) or await get_user_status(bot, chat_id, user_id) in GROUP_ADMIN_STATUSES


async def reviewer_ids(bot: Bot, chat_id: int) -> list[int]:
    """Shu guruhning anketa/qaror adminlari: Telegram guruh adminlari (botlarsiz) va ADMIN_IDS."""
    ids = dict.fromkeys(ADMIN_IDS)
    try:
        for member in await bot.get_chat_administrators(chat_id):
            if not member.user.is_bot:
                ids[member.user.id] = None
    except TelegramAPIError as e:
        logger.warning("Guruh adminlari ro'yxatini olib bo'lmadi (chat_id=%s): %r", chat_id, e)
    return list(ids)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def notify_admins(bot: Bot, group_id: int, text: str, *, exclude: tuple[int, ...] = ()) -> None:
    """Guruhning barcha adminlariga (exclude dagilardan tashqari) qisqa xabar; yetmaganlari jim o'tkaziladi."""
    await asyncio.gather(
        *(safe_send(bot=bot, chat_id=a, text=text) for a in await reviewer_ids(bot, group_id) if a not in exclude),
        return_exceptions=True,
    )


def status_text(app: dict, accepted: bool, note: str = "") -> str:
    """Ovoz natijasi bo'yicha adminlarga status: «Ism Familiya guruhga qabul qilindi/qilinmadi»."""
    name = escape(app["full_name"])
    if accepted:
        return f"✅ <b>{name}</b> guruhga qabul qilindi{note}"
    return f"❌ <b>{name}</b> guruhga qabul qilinmadi{note}"


def join_failed_text(app: dict) -> str:
    """Ariza qabul qilindi, lekin guruhga qo'shib bo'lmadi: adminlar bilishi kerak."""
    return (
        f"⚠️ <b>{escape(app['full_name'])}</b> arizasi qabul qilindi, lekin guruhga qo'shib bo'lmadi "
        "(so'rov bekor qilingan yoki botda huquq yetmaydi). Foydalanuvchi qayta so'rov yuborishi kerak."
    )


async def mark_done(call: CallbackQuery, result: str):
    """Admin xabaridagi tugmalarni olib, natija va qaror qilgan admin ismini yozadi."""
    if isinstance(call.message, Message):
        who = escape(call.from_user.full_name)
        try:
            await call.message.edit_text(f"{call.message.html_text}\n\n{result} · {who}")
        except TelegramBadRequest:
            pass
