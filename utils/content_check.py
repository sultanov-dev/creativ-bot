"""Xabar mazmunini tekshirish: guruh (handlers/ads.py) va lichkadagi admin suhbati (handlers/support.py) uchun BITTA joy.

Tartib (avval bot o'zi, AI faqat kerak bo'lganda):
1. 18+ media (utils/nsfw.py): rasm, stiker, video, GIF, video-xabar, rasm-fayl — NudeNet, kerak bo'lsa AI.
2. Matn: xabar/izoh, so'rovnoma, joy, kontakt + rasm ichidagi yozuv va QR-kod (utils/media_text.py) — havolalar,
   Telegram havolalari va kanal forwardlari, reklama (utils/ads.py, utils/tg_links.py, utils/url_check.py).

Natijada nima qilish (o'chirish, ogohlantirish, AI suhbatga eslatma) chaqiruvchining ishi; tekshiruvning o'zi shu yerda.
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from utils import ads, media_text, nsfw, tg_links
from utils.ads import AD, DANGER, classify, find_urls
from utils.profanity import has_adult_content, has_profanity

logger = logging.getLogger(__name__)

NSFW = nsfw.NSFW
IMAGE_TEXT_MARK = "🖼"  # harfsiz: "izohsiz havola" qoidasida so'z bo'lib sanalmaydi

# guruh haqida (getChat): username va bog'langan kanal; soatda bir yangilanadi
_chat_info: dict[int, tuple[str | None, int | None, float]] = {}
CHAT_INFO_TTL = 3600

Exempt = Callable[[], Awaitable[bool]]


@dataclass
class Inspection:
    verdict: str | None  # NSFW | DANGER | AD | None
    text: str  # tekshirilgan matn: xabar matni + rasmdagi yozuv (🖼 belgisidan keyin)


def message_text(message: Message) -> str:
    """Tekshiriladigan matn: xabar/izoh, so'rovnoma savoli va javoblari, joy nomi va manzili, kontakt."""
    parts = [message.text or message.caption or ""]
    if message.poll:
        parts += [message.poll.question, *(o.text for o in message.poll.options)]
    if message.venue:
        parts += [message.venue.title, message.venue.address]
    if message.contact:
        c = message.contact
        parts += [" ".join(p for p in (c.first_name, c.last_name) if p), c.phone_number]
    return "\n".join(p for p in parts if p)


def forwarded_channel(message: Message) -> tg_links.TgLink | None:
    origin = getattr(message, "forward_origin", None)
    if origin is None or getattr(origin, "type", None) != "channel":
        return None
    chat = origin.chat
    return tg_links.from_channel(chat.id, chat.username, chat.title)


async def group_info(bot: Bot, chat_id: int) -> tuple[str | None, int | None]:
    """Guruhning username'i va bog'langan kanali (o'z havolalari va o'z kanali reklama emas)."""
    cached = _chat_info.get(chat_id)
    now = time.monotonic()
    if cached and cached[2] > now:
        return cached[0], cached[1]
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramAPIError as e:
        logger.warning("Guruh ma'lumotini olib bo'lmadi (chat=%s): %s", chat_id, e)
        return (cached[0], cached[1]) if cached else (None, None)
    _chat_info[chat_id] = (chat.username, chat.linked_chat_id, now + CHAT_INFO_TTL)
    return chat.username, chat.linked_chat_id


async def _never_exempt() -> bool:
    return False


async def media_verdict(bot: Bot, message: Message) -> str | None:
    """18+ media bo'lsa NSFW."""
    if nsfw.media_of(message) is None:
        return None
    return NSFW if await nsfw.check_message(bot, message) else None


async def full_text(bot: Bot, message: Message, *, read_media: bool = True) -> str:
    """Xabar matni + rasm/stiker/video muqovasidagi yozuv va QR-kod (entity'lar siljimasligi uchun oxiriga)."""
    text = message_text(message)
    if read_media and nsfw.media_of(message) is not None:
        image_text = await media_text.extract(bot, message)
        if image_text:
            text = f"{text}\n{IMAGE_TEXT_MARK}\n{image_text}" if text else f"{IMAGE_TEXT_MARK}\n{image_text}"
    return text


LateVerdict = Callable[[str], Awaitable[object]]
_background: set[asyncio.Task] = set()  # fondagi AI tekshiruvlari (GC yig'ib olmasin; testlar drain() bilan kutadi)


async def drain() -> None:
    """Fondagi AI tekshiruvlari tugashini kutadi (testlar va to'xtash uchun)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


async def _ai_decision(text: str, urls: list[str], forwarded, kind: str, group_id, username, linked) -> str | None:
    verdict = await ads.ai_verdict(text, urls, forwarded.url if forwarded else None)
    if verdict in (AD, DANGER):
        own = [*map(tg_links.parse, urls), forwarded]
        tg_links.remember_ad(
            [link for link in own if link is not None and not tg_links.is_own(link, group_id, username, linked)]
        )  # shu manzil yana kelsa, AI chaqirilmaydi
        return verdict
    if verdict is None and kind == "telegram":
        # AI ishlamadi: begona Telegram havolasi o'chiriladi (uzilish reklamaga yo'l ochmasin)
        return AD
    return None


async def _late(on_late: LateVerdict, *args) -> None:
    try:
        verdict = await _ai_decision(*args)
        if verdict is not None:
            await on_late(verdict)
    except Exception:
        logger.exception("Fondagi AI tekshiruvi yiqildi")


async def text_verdict(
    bot: Bot,
    message: Message,
    text: str,
    *,
    group_id: int | None,
    exempt: Exempt = _never_exempt,
    on_late: LateVerdict | None = None,
) -> str | None:
    """Matn, havolalar va kanal forwardi bo'yicha: DANGER, AD yoki None. `group_id` — o'z guruhi (uning havolalari
    va bog'langan kanali shubha emas). `exempt` faqat shubha topilganda chaqiriladi (ortiqcha API so'rovisiz).

    Avval kod qaror qiladi (darhol). AI kerak bo'lsa: `on_late` berilgan bo'lsa AI fonda ishlaydi, bu funksiya
    darhol None qaytaradi va hukm AD/DANGER bo'lsa keyinroq `on_late(hukm)` chaqiriladi (guruh: hech kim AI'ni
    kutmaydi); berilmasa AI javobi kutiladi (lichkadagi suhbat).
    """
    entities = message.entities or message.caption_entities
    forwarded = forwarded_channel(message)
    username, linked = (None, None)
    if group_id is not None:
        if message.chat.id == group_id:
            username = message.chat.username
            linked = (await group_info(bot, group_id))[1] if forwarded else None
        else:  # lichka: guruh haqidagi ma'lumot keshdan
            username, linked = await group_info(bot, group_id)
    kind = classify(
        text,
        entities,
        forwarded_from=forwarded,
        markup=message.reply_markup,
        chat_id=group_id,
        chat_username=username,
        linked_chat_id=linked,
    )
    if kind is None or await exempt():
        return None
    if kind == "danger":
        return DANGER
    if kind == "definite":
        return AD
    args = (text, find_urls(text, entities, message.reply_markup), forwarded, kind, group_id, username, linked)
    if on_late is None:
        return await _ai_decision(*args)
    task = asyncio.create_task(_late(on_late, *args))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return None


async def inspect(bot: Bot, message: Message, *, group_id: int | None, exempt: Exempt = _never_exempt) -> Inspection:
    """Hammasi bir joyda: avval 18+ media, keyin matn (rasmdagi yozuv bilan) va havolalar."""
    if await media_verdict(bot, message) == NSFW and not await exempt():
        return Inspection(NSFW, message_text(message))
    text = await full_text(bot, message)
    return Inspection(await text_verdict(bot, message, text, group_id=group_id, exempt=exempt), text)


# botning o'z matni uchun: oddiy havola (masalan hujjatga) mumkin, Telegram kanal/bot havolasi va xavflisi mumkin emas
_UNSAFE_LINK_KINDS = ("danger", "definite", "telegram")


def unsafe_reply(text: str, *, chat_id: int | None, chat_username: str | None) -> str | None:
    """Bot guruhga o'zi yozadigan matn (AI javobi) uchun, AI'siz: "profanity", "adult", "link" yoki None.

    AI'ni foydalanuvchi aldab (prompt injection) bot nomidan reklama, havola yoki odobsiz matn yozdirmasligi uchun.
    """
    if has_profanity(text):
        return "profanity"
    if has_adult_content(text):
        return "adult"
    if classify(text, None, chat_id=chat_id, chat_username=chat_username) in _UNSAFE_LINK_KINDS:
        return "link"
    return None


def _size(n: int | None) -> str:
    if not n:
        return ""
    return f", {n // 1024} KB" if n < 1024 * 1024 else f", {n / 1024 / 1024:.1f} MB"


def describe(message: Message, text: str) -> str:
    """Xabarning matnli tavsifi (AI suhbat tarixi va adminga xulosa uchun): nima yuborilgani + o'qilgan matn.

    `text` — full_text() natijasi (xabar matni, rasmdagi yozuv 🖼 belgisidan keyin). Faylning o'zi hech qayerga
    yuborilmaydi: AI ham, admin ham faqat shu tavsifni ko'radi.
    """
    kinds = []
    if message.photo:
        kinds.append("rasm")
    if message.sticker:
        kinds.append(f"stiker {message.sticker.emoji or ''}".strip())
    if message.animation:
        kinds.append("GIF")
    elif message.video:
        kinds.append(f"video, {message.video.duration} s")
    if message.video_note:
        kinds.append(f"dumaloq video, {message.video_note.duration} s")
    if message.voice:
        kinds.append(f"ovozli xabar, {message.voice.duration} s, matni o'qilmagan")
    if message.audio:
        kinds.append(f"audio: {message.audio.title or message.audio.file_name or ''}{_size(message.audio.file_size)}")
    if message.document and not message.animation:
        kinds.append(f"fayl: {message.document.file_name or 'nomsiz'}{_size(message.document.file_size)}")
    if message.location and not message.venue:
        kinds.append("joylashuv")
    if message.venue:
        kinds.append("manzil")
    if message.contact:
        kinds.append("kontakt")
    if message.poll:
        kinds.append("so'rovnoma")
    forwarded = forwarded_channel(message)
    if forwarded is not None:
        kinds.append(f"kanaldan forward: {forwarded.url}")
    elif getattr(message, "forward_origin", None) is not None:
        kinds.append("forward qilingan xabar")
    head = f"[{'; '.join(kinds)}]" if kinds else ""
    body = text.replace(f"\n{IMAGE_TEXT_MARK}\n", "\n[rasmdagi yozuv] ").replace(f"{IMAGE_TEXT_MARK}\n", "[rasmdagi yozuv] ")
    return "\n".join(p for p in (head, body) if p)
