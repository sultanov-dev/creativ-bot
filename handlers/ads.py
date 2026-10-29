import logging
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from texts import AD_NOTICE, LINK_DANGER_NOTICE, NSFW_NOTICE
from utils.admin import get_user_status, is_admin
from utils import content_check
from utils.ads import DANGER

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.edited_message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = logging.getLogger(__name__)

# bir foydalanuvchiga ogohlantirish xabari ko'pi bilan daqiqada bir marta (spamer botni to'ldirib yubormasin)
_warned: dict[int, float] = {}
WARN_INTERVAL = 60
_WARNED_MAX = 1000


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


async def is_nsfw(message: Message, bot: Bot) -> dict | bool:
    """Filtr: rasm, stiker, video, GIF, video-xabar yoki rasm-fayl 18+ bo'lsa {"verdict": "nsfw"}."""
    user = message.from_user
    if user is not None and is_admin(user.id):
        return False  # bot adminlarining mediasi yuklab ham olinmaydi
    if await content_check.media_verdict(bot, message) is None or await _exempt(bot, message):
        return False
    return {"verdict": content_check.NSFW}


async def is_advertisement(message: Message, bot: Bot) -> dict | bool:
    """Filtr: reklama yoki xavfli havola bo'lsa {"verdict": ...}, aks holda False (boshqa routerlar, masalan AI, xabarni ko'radi)."""
    user = message.from_user
    text = await content_check.full_text(bot, message, read_media=not (user is not None and is_admin(user.id)))
    # kod aniq topganini darhol qaytaradi; AI kerak bo'lsa u fonda ishlaydi, reklama chiqsa xabar keyinroq o'chadi
    verdict = await content_check.text_verdict(
        bot,
        message,
        text,
        group_id=message.chat.id,
        exempt=lambda: _exempt(bot, message),
        on_late=lambda late: remove_advertisement(message, bot, late),
    )
    return {"verdict": verdict} if verdict else False


# dekoratorlar pastdan yuqoriga ro'yxatdan o'tadi: avval 18+ media (AI'siz model), keyin reklama/havola
@router.message(is_advertisement)
@router.edited_message(is_advertisement)
@router.message(is_nsfw)
@router.edited_message(is_nsfw)
async def remove_advertisement(message: Message, bot: Bot, verdict: str):
    user = message.from_user
    try:
        await message.delete()
    except TelegramAPIError as e:
        logger.warning("Reklamani o'chirib bo'lmadi (chat=%s, message=%s): %s", message.chat.id, message.message_id, e)
        return
    kind = {DANGER: "Xavfli havola", content_check.NSFW: "18+ kontent"}.get(verdict, "Reklama")
    logger.info("%s o'chirildi: chat=%s user=%s", kind, message.chat.id, user.id if user else None)

    now = time.monotonic()
    if user is None or now - _warned.get(user.id, -WARN_INTERVAL) < WARN_INTERVAL:
        return
    if len(_warned) >= _WARNED_MAX:
        for uid in [u for u, t in _warned.items() if now - t >= WARN_INTERVAL]:
            del _warned[uid]
    _warned[user.id] = now
    # bu xabar ham AUTO_DELETE_SECONDS dan keyin o'chadi
    notice = {DANGER: LINK_DANGER_NOTICE, content_check.NSFW: NSFW_NOTICE}.get(verdict, AD_NOTICE)
    await bot.send_message(chat_id=message.chat.id, text=notice.format(name=escape(user.full_name)))
