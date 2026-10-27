import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from database import get_unresolved_join_requests, mark_join_resolved
from utils.admin import is_group_member, join_failed_text, notify_admins

logger = logging.getLogger(__name__)


async def _call(method, app: dict) -> TelegramAPIError | None:
    for attempt in range(2):
        try:
            await method(chat_id=app["group_id"], user_id=app["user_id"])
            return None
        except TelegramRetryAfter as e:
            if attempt == 1:
                return e
            await asyncio.sleep(min(e.retry_after, 5))
        except TelegramAPIError as e:
            return e
    return None  # pragma: no cover


async def settle_join_request(bot: Bot, app: dict, accept: bool) -> bool:
    """Guruh so'rovini tasdiqlaydi yoki rad etadi va natijani bazaga yozadi.

    False faqat: ariza qabul qilingan, lekin so'rov bajarilmadi va foydalanuvchi guruhda emas
    (so'rov bekor qilingan yoki botda huquq yo'q). Rad etishda xato muhim emas (so'rov allaqachon yo'q).
    """
    err = await _call(bot.approve_chat_join_request if accept else bot.decline_chat_join_request, app)
    joined = True
    if err is not None:
        if accept:
            joined = await is_group_member(bot, app["group_id"], app["user_id"])
            if not joined:
                logger.warning("Ariza %s: so'rovni tasdiqlab bo'lmadi: %r", app["id"], err)
        else:
            logger.info("Ariza %s: so'rovni rad etishda xato (e'tiborsiz): %r", app["id"], err)
    await mark_join_resolved(app["id"])
    return joined


async def recover_unresolved(bot: Bot) -> int:
    """Startda: holati yozilgan, lekin bot to'xtagani uchun so'rovi bajarilmagan arizalarni tugatadi."""
    done = 0
    for app in await get_unresolved_join_requests():
        accepted = app["status"] == "accepted"
        joined = await settle_join_request(bot, app, accepted)
        if accepted and not joined:
            await notify_admins(bot, join_failed_text(app))
        logger.info("Ariza %s: to'xtab qolgan so'rov qayta bajarildi (%s)", app["id"], app["status"])
        done += 1
    return done
