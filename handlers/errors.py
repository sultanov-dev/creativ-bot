import logging
from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from config import ADMIN_IDS
from texts import ERROR_GENERIC
from utils.admin import safe_send

router = Router()
logger = logging.getLogger(__name__)


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    """Handlerlarda ushlanmagan xatolar: log, foydalanuvchiga xabar va ADMIN_IDS ga ogohlantirish."""
    exc = event.exception
    update = event.update
    logger.error("Ushlanmagan xatolik: %r", exc, exc_info=exc)

    try:
        if update.callback_query:
            await update.callback_query.answer(ERROR_GENERIC, show_alert=True)
        elif update.message and update.message.chat.type == "private":
            await update.message.answer(ERROR_GENERIC)
    except TelegramAPIError:
        pass

    for admin_id in ADMIN_IDS:
        await safe_send(
            bot=bot,
            chat_id=admin_id,
            text=f"⚠️ Bot xatosi: <code>{escape(type(exc).__name__)}: {escape(str(exc))[:300]}</code>",
        )

    return True
