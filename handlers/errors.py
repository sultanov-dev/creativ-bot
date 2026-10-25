import logging
import time
from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import ErrorEvent, Update

from config import DEVELOPER_IDS
from texts import ERROR_GENERIC
from utils.admin import safe_send

router = Router()
logger = logging.getLogger(__name__)

ALERT_COOLDOWN = 300
_last_alert: dict[str, float] = {}

BENIGN_MARKERS = (
    "query is too old",
    "message is not modified",
    "bot was blocked by the user",
    "user is deactivated",
    "message to edit not found",
)


def _is_benign(exc: BaseException) -> bool:
    """Dasturchiga ham, foydalanuvchiga ham ogohlantirish kerak bo'lmagan Telegram xatolari."""
    return isinstance(exc, (TelegramBadRequest, TelegramForbiddenError)) and any(
        marker in str(exc).lower() for marker in BENIGN_MARKERS
    )


def _context(update: Update) -> str:
    """Xato qayerda va kim bilan bo'lganini aytadigan qisqa matn (debug uchun)."""
    event = update.event
    chat = getattr(event, "chat", None) or getattr(
        getattr(event, "message", None), "chat", None
    )
    user = getattr(event, "from_user", None)
    return (
        f"update: {update.event_type}, "
        f"chat: {chat.id if chat else '-'}, "
        f"user: {user.id if user else '-'}"
    )


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    """Handlerlarda ushlanmagan xatolar: log, foydalanuvchiga xabar, dasturchiga (DEVELOPER_IDS) ogohlantirish."""
    exc = event.exception
    update = event.update

    if _is_benign(exc):
        logger.warning("Zararsiz Telegram xatosi: %r", exc)
        return True

    logger.error("Ushlanmagan xatolik: %r", exc, exc_info=exc)

    try:
        if update.callback_query:
            await update.callback_query.answer(ERROR_GENERIC, show_alert=True)
        elif update.message and update.message.chat.type == "private":
            await update.message.answer(ERROR_GENERIC)
    except TelegramAPIError:
        pass

    # bir xil xato uchun dasturchiga 5 daqiqada bir martadan ko'p yozmaymiz
    alert_key = f"{type(exc).__name__}:{exc}"
    now = time.monotonic()
    if now - _last_alert.get(alert_key, -ALERT_COOLDOWN) < ALERT_COOLDOWN:
        return True
    _last_alert[alert_key] = now

    text = (
        f"⚠️ Bot xatosi: <code>{escape(type(exc).__name__)}: {escape(str(exc))[:300]}</code>\n"
        f"{escape(_context(update))}"
    )
    for developer_id in DEVELOPER_IDS:
        await safe_send(bot=bot, chat_id=developer_id, text=text)

    return True
