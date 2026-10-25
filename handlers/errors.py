import logging
from html import escape

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import ErrorEvent, Update

from callbacks import ApplicantCB, VoteCB
from config import ADMIN_IDS
from database import get_application
from texts import ERROR_GENERIC
from utils.admin import safe_send

router = Router()
logger = logging.getLogger(__name__)

GROUP_TYPES = ("group", "supergroup")


async def _find_group_id(update: Update, state: FSMContext | None) -> int | None:
    """Xato qaysi guruhga tegishli ekanini yangilanishdan aniqlaydi."""
    for event in (update.message, update.chat_join_request, update.my_chat_member):
        chat = getattr(event, "chat", None)
        if chat and chat.type in GROUP_TYPES:
            return chat.id

    cb = update.callback_query
    if cb and cb.data:
        for cb_class in (ApplicantCB, VoteCB):
            try:
                app_id = cb_class.unpack(cb.data).app_id
            except (TypeError, ValueError):
                continue
            app = await get_application(app_id)
            return app["group_id"] if app else None

    if state is not None:
        return (await state.get_data()).get("group_id")
    return None


async def _creator_id(bot: Bot, group_id: int) -> int | None:
    try:
        admins = await bot.get_chat_administrators(group_id)
    except TelegramAPIError:
        return None
    return next(
        (a.user.id for a in admins if a.status == ChatMemberStatus.CREATOR), None
    )


@router.errors()
async def on_error(event: ErrorEvent, bot: Bot, state: FSMContext | None = None) -> bool:
    """Handlerlarda ushlanmagan xatolar: log, foydalanuvchiga xabar, guruh creator'iga ogohlantirish."""
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

    recipients = set(ADMIN_IDS)
    try:
        group_id = await _find_group_id(update, state)
    except Exception:
        logger.exception("Xato guruhini aniqlab bo'lmadi")
        group_id = None
    if group_id is not None:
        creator = await _creator_id(bot, group_id)
        if creator is not None:
            recipients.add(creator)

    text = f"⚠️ Bot xatosi: <code>{escape(type(exc).__name__)}: {escape(str(exc))[:300]}</code>"
    for chat_id in recipients:
        await safe_send(bot=bot, chat_id=chat_id, text=text)

    return True
