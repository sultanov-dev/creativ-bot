from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS


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
    """Bot admini: faqat ADMIN_IDS ro'yxati (.env) hisoblanadi."""
    return user_id in ADMIN_IDS


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def mark_done(call: CallbackQuery, result: str):
    """Admin xabaridagi tugmalarni olib, natija va qaror qilgan admin ismini yozadi."""
    if isinstance(call.message, Message):
        who = escape(call.from_user.full_name)
        try:
            await call.message.edit_text(f"{call.message.html_text}\n\n{result} · {who}")
        except TelegramBadRequest:
            pass
