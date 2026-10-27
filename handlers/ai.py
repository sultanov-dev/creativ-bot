import asyncio
import re
import time
from collections import OrderedDict

from aiogram import Bot, F, Router
from aiogram.enums import MessageEntityType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

import texts
from utils.ai import AIError, ask_ai
from utils.ai_html import plain_text, sanitize_html
from utils.autodelete import keep_messages
from utils.lang import detect_lang

router = Router()
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

MAX_QUESTION = 2000
TG_LIMIT = 4096
COOLDOWN = 5
# uzun javob guruhni xabarlar bilan to'ldirmasligi va flood-limitga urilmasligi uchun
MAX_PARTS = 2

_last_ask: dict[int, float] = {}
_LAST_ASK_MAX = 1000
# botning AI javoblari (chat_id, message_id): shularga reply qilinsa suhbat davom etadi
_ai_messages: OrderedDict[tuple[int, int], None] = OrderedDict()
_AI_MESSAGES_MAX = 1000


def _remember(message: Message) -> None:
    _ai_messages[(message.chat.id, message.message_id)] = None
    if len(_ai_messages) > _AI_MESSAGES_MAX:
        _ai_messages.popitem(last=False)


def _is_mentioned(message: Message, username: str) -> bool:
    text = message.text or ""
    return any(
        e.type == MessageEntityType.MENTION
        and e.extract_from(text).lower() == f"@{username.lower()}"
        for e in message.entities or []
    )


def _is_ai_reply(message: Message) -> bool:
    reply = message.reply_to_message
    return reply is not None and (reply.chat.id, reply.message_id) in _ai_messages


async def addressed(message: Message, bot: Bot) -> bool:
    me = await bot.me()
    return _is_mentioned(message, me.username or "") or _is_ai_reply(message)


def _split(text: str) -> list[str]:
    """4096 belgidan oshmaydigan bo'laklar; imkon bo'lsa qator oxirida bo'linadi (teg o'rtasida emas)."""
    parts = []
    while len(text) > TG_LIMIT:
        cut = text.rfind("\n", 0, TG_LIMIT)
        cut = cut if cut > 0 else TG_LIMIT
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


async def _reply_part(message: Message, part: str) -> Message:
    """Xavfsizlashtirilgan HTML bilan; Telegram qabul qilmasa, oddiy matn bilan."""
    with keep_messages():  # AI javobi o'chmaydi: unga reply qilib suhbatni davom ettirish mumkin
        try:
            return await message.reply(sanitize_html(part))
        except TelegramBadRequest:
            return await message.reply(plain_text(part), parse_mode=None)


async def _send_loading(message: Message, lang: str) -> Message:
    # javob kelgach o'zimiz o'chiramiz, shuning uchun avto-o'chirish navbatiga qo'shilmaydi
    with keep_messages():
        return await message.reply(texts.AI_LOADING[lang])


async def _remove_loading(task: "asyncio.Task[Message]") -> None:
    """"Yuklanmoqda" xabarini o'chiradi (yuborilmagan yoki allaqachon o'chgan bo'lsa, jim o'tadi)."""
    try:
        await (await task).delete()
    except TelegramAPIError:
        pass


@router.message(F.text, ~F.text.startswith("/"), addressed)
async def on_ai_question(message: Message, bot: Bot):
    if message.from_user is None or message.text is None:
        return
    me = await bot.me()
    username = me.username or ""

    question = re.sub(
        rf"@{re.escape(username)}(?![A-Za-z0-9_])", "", message.text, flags=re.IGNORECASE
    ).strip()
    reply = message.reply_to_message
    quoted = (reply.text or reply.caption) if reply else None

    if not question:
        await message.reply(texts.AI_EMPTY.format(username=username))
        return
    if len(question) > MAX_QUESTION:
        await message.reply(texts.AI_TOO_LONG)
        return

    now = time.monotonic()
    if now - _last_ask.get(message.from_user.id, -COOLDOWN) < COOLDOWN:
        await message.reply(texts.AI_COOLDOWN)
        return
    if len(_last_ask) >= _LAST_ASK_MAX:
        # cooldown'i o'tgan yozuvlar keraksiz: xotira o'sib ketmasin
        for uid in [u for u, t in _last_ask.items() if now - t >= COOLDOWN]:
            del _last_ask[uid]
    _last_ask[message.from_user.id] = now

    history = [{"role": "system", "content": texts.AI_SYSTEM_PROMPT}]
    if quoted and _is_ai_reply(message):
        history.append({"role": "assistant", "content": quoted})
    elif quoted:
        question = f"Xabar: {quoted[:MAX_QUESTION]}\n\nSavol: {question}"
    history.append({"role": "user", "content": question})

    # "yuklanmoqda" xabari AI so'rovi bilan parallel yuboriladi: javobni kechiktirmaydi
    loading = asyncio.create_task(_send_loading(message, detect_lang(question)))
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            answer = await ask_ai(history)
    except AIError:
        await _remove_loading(loading)
        await message.reply(texts.AI_ERROR)
        raise
    except BaseException:
        loading.cancel()
        raise
    await _remove_loading(loading)

    for part in _split(answer)[:MAX_PARTS]:
        _remember(await _reply_part(message, part))
