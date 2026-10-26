from html import escape

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message


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


async def is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    status = await get_user_status(bot, chat_id, user_id)

    return status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def get_group_creator_id(bot: Bot, chat_id: int) -> int | None:
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return None
    for a in admins:
        if a.status == ChatMemberStatus.CREATOR:
            return a.user.id
    return None


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False


async def mark_done(
    call: CallbackQuery, result: str, bot: Bot, chat_id: int, user_id: int
):
    status = await get_user_status(bot, chat_id, user_id)

    if isinstance(call.message, Message):
        who = escape(call.from_user.full_name)
        # aiogram status'ni ba'zan oddiy str, ba'zan enum qaytaradi
        role = str(getattr(status, "value", status)) if status else "noma'lum"
        try:
            await call.message.edit_text(
                f"{call.message.html_text}\n\n{result} · {who} ({role})"
            )
        except TelegramBadRequest:
            pass
