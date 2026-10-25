from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from database import get_no_reasons
from utils.admin import safe_send


async def _group_admin_ids(bot: Bot, group_id: int) -> list[int]:
    try:
        admins = await bot.get_chat_administrators(chat_id=group_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        return []
    return [a.user.id for a in admins if not a.user.is_bot]


async def _voter_name(bot: Bot, group_id: int, voter_id: int) -> str:
    try:
        member = await bot.get_chat_member(group_id, voter_id)
        return escape(member.user.full_name)
    except (TelegramBadRequest, TelegramForbiddenError):
        return str(voter_id)


async def send_to_admins(bot: Bot, group_id: int, text: str) -> None:
    for admin_id in await _group_admin_ids(bot, group_id):
        await safe_send(bot=bot, chat_id=admin_id, text=text)


async def send_reasons_summary(bot: Bot, app: dict, result: str) -> None:
    """Ovoz berish yakunlanganda yig'ilgan "yo'q" sabablarini adminlarga yuboradi."""
    reasons = await get_no_reasons(app["id"])
    if not reasons:
        return

    lines = [
        f"📋 <b>{escape(app['full_name'])}</b> arizasi bo'yicha 👎 sabablari ({result}):\n"
    ]
    for voter_id, reason in reasons:
        name = await _voter_name(bot, app["group_id"], voter_id)
        lines.append(f"• <b>{name}</b>: {escape(reason)}")

    await send_to_admins(bot, app["group_id"], "\n".join(lines))
