import logging
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from texts import AD_NOTICE, LINK_DANGER_NOTICE
from utils.admin import get_user_status, is_admin
from utils.ads import AD, DANGER, ai_verdict, classify, find_urls

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.edited_message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = logging.getLogger(__name__)

# bir foydalanuvchiga ogohlantirish xabari ko'pi bilan daqiqada bir marta (spamer botni to'ldirib yubormasin)
_warned: dict[int, float] = {}
WARN_INTERVAL = 60
_WARNED_MAX = 1000


def _from_channel(message: Message) -> bool:
    origin = getattr(message, "forward_origin", None)
    return origin is not None and getattr(origin, "type", None) == "channel"


async def _exempt(bot: Bot, message: Message) -> bool:
    """Bot adminlari, guruh adminlari, anonim admin, bog'langan kanal posti va botlar tekshirilmaydi."""
    user = message.from_user
    if user is None or user.is_bot:
        return True
    if message.sender_chat is not None and message.sender_chat.id == message.chat.id:
        return True  # guruh nomidan yozgan anonim admin
    if message.is_automatic_forward:
        return True  # bog'langan kanaldan avtomatik post
    if is_admin(user.id):
        return True
    status = await get_user_status(bot, message.chat.id, user.id)
    return str(getattr(status, "value", status)) in ("administrator", "creator")


async def is_advertisement(message: Message, bot: Bot) -> dict | bool:
    """Filtr: reklama yoki xavfli havola bo'lsa {"verdict": ...}, aks holda False (boshqa routerlar, masalan AI, xabarni ko'radi)."""
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities
    kind = classify(text, entities, forwarded_from_channel=_from_channel(message), markup=message.reply_markup)
    if kind is None:
        return False
    if await _exempt(bot, message):
        return False
    if kind == "danger":
        return {"verdict": DANGER}
    if kind == "definite":
        return {"verdict": AD}
    verdict = await ai_verdict(text, find_urls(text, entities, message.reply_markup))
    return {"verdict": verdict} if verdict else False


@router.message(is_advertisement)
@router.edited_message(is_advertisement)
async def remove_advertisement(message: Message, bot: Bot, verdict: str):
    user = message.from_user
    try:
        await message.delete()
    except TelegramAPIError as e:
        logger.warning("Reklamani o'chirib bo'lmadi (chat=%s, message=%s): %s", message.chat.id, message.message_id, e)
        return
    logger.info("%s o'chirildi: chat=%s user=%s", "Xavfli havola" if verdict == DANGER else "Reklama",
                message.chat.id, user.id if user else None)

    now = time.monotonic()
    if user is None or now - _warned.get(user.id, -WARN_INTERVAL) < WARN_INTERVAL:
        return
    if len(_warned) >= _WARNED_MAX:
        for uid in [u for u, t in _warned.items() if now - t >= WARN_INTERVAL]:
            del _warned[uid]
    _warned[user.id] = now
    # bu xabar ham AUTO_DELETE_SECONDS dan keyin o'chadi
    notice = LINK_DANGER_NOTICE if verdict == DANGER else AD_NOTICE
    await bot.send_message(chat_id=message.chat.id, text=notice.format(name=escape(user.full_name)))
