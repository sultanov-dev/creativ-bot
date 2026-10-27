import asyncio
import logging
import time
from collections import defaultdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

import texts
from config import ADMIN_IDS, SUPPORT_MAX_TURNS, SUPPORT_TTL_HOURS
from database import (
    add_support_message,
    create_support_chat,
    get_support_chat,
    get_support_messages,
    set_support_status,
)
from utils.admin import safe_send
from utils.ai import AIError, ask_ai_tools
from utils.ai_html import plain_text, sanitize_html
from utils.lang import detect_lang

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)

MAX_TEXT = 2000
GROUP_PREFIX = "[Guruhdagi xabar]"
WAIT_NOTICE_INTERVAL = 60

# guruhda AI shu tool'ni chaqirsa, bot foydalanuvchining lichkasiga yozadi (guruhda javob yozilmaydi)
CONTACT_ADMIN_TOOL = {
    "type": "function",
    "function": {
        "name": "contact_admin",
        "description": (
            "The user wants to talk to an admin, moderator or the group owner (any wording or language, also "
            "indirectly). Call it instead of answering in the group."
        ),
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string", "description": "Why the user wants an admin, briefly."}},
        },
    },
}
ESCALATE_TOOL = {
    "type": "function",
    "function": {
        "name": "escalate_to_admin",
        "description": "Pass a serious matter to the admins together with a summary of everything the user said.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Summary for the admin, in Uzbek: who wants what and all details."}
            },
            "required": ["summary"],
        },
    },
}
RESOLVE_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve",
        "description": "The user's problem is solved or they have no more questions: close the conversation.",
        "parameters": {"type": "object", "properties": {}},
    },
}
SUPPORT_TOOLS = [ESCALATE_TOOL, RESOLVE_TOOL]

# bir foydalanuvchining xabarlari ketma-ket ishlansin (AI javobi kelguncha yana yozsa, suhbat chalkashmasin)
_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_last_wait: dict[int, float] = {}
_LAST_WAIT_MAX = 1000


def _fallback_summary(messages: list[dict]) -> str:
    """AI summary bermasa: foydalanuvchining o'z gaplari."""
    lines = [m["content"] for m in messages if m["role"] == "user"]
    return "\n".join(f"• {line[:500]}" for line in lines[-SUPPORT_MAX_TURNS:])


async def _send(bot: Bot, user_id: int, text: str) -> None:
    """Xavfsizlashtirilgan HTML bilan; Telegram qabul qilmasa, oddiy matn bilan. Yetkazib bo'lmasa xato ko'taradi."""
    try:
        await bot.send_message(user_id, sanitize_html(text)[:4096])
    except TelegramBadRequest as e:
        if "parse" not in str(e).lower():
            raise
        await bot.send_message(user_id, plain_text(text)[:4096], parse_mode=None)


async def _notify_admins(bot: Bot, chat: dict, summary: str) -> int:
    username = f" (@{escape(chat['tg_username'])})" if chat["tg_username"] else ""
    text = texts.SUPPORT_ADMIN_NOTICE.format(
        user_id=chat["user_id"],
        name=escape(chat["full_name"]),
        username=username,
        group=escape(chat["group_title"] or str(chat["group_id"])),
        summary=escape(summary[:3000]),
    )
    results = await asyncio.gather(*(safe_send(bot, a, text) for a in ADMIN_IDS), return_exceptions=True)
    return sum(r is True for r in results)


async def _escalate(bot: Bot, chat: dict, summary: str, lang: str) -> None:
    if not await set_support_status(chat["id"], "active", "escalated"):
        return  # allaqachon uzatilgan yoki yopilgan
    if await _notify_admins(bot, chat, summary) == 0:
        # hech bir adminga yetmadi: foydalanuvchiga "yubordim" deb aytib bo'lmaydi
        logger.error("Support so'rovi hech bir adminga yetmadi (chat_id=%s, ADMIN_IDS=%s)", chat["id"], len(ADMIN_IDS))
        await set_support_status(chat["id"], "escalated", "active")
        await safe_send(bot, chat["user_id"], texts.SUPPORT_ADMIN_UNAVAILABLE[lang])
        return
    await safe_send(bot, chat["user_id"], texts.SUPPORT_ESCALATED[lang])


async def run_turn(bot: Bot, chat: dict) -> None:
    """Saqlangan suhbat bo'yicha AI javobi: matnni foydalanuvchiga yuboradi, tool chaqirsa bajaradi."""
    messages = await get_support_messages(chat["id"])
    # limit lichkadagi xabarlarga: guruhdan ko'chirilgan birinchi xabar hisobga kirmaydi
    user_turns = sum(m["role"] == "user" and not m["content"].startswith(GROUP_PREFIX) for m in messages)
    last = user_turns >= SUPPORT_MAX_TURNS
    history = [{"role": "system", "content": texts.SUPPORT_SYSTEM_PROMPT}, *messages]
    if last:
        # majburlamaymiz: AI oxirgi yechimini aytib resolve qilishi yoki escalate_to_admin qilishi mumkin
        history.append({"role": "system", "content": texts.SUPPORT_LAST_TURN})

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat["user_id"]):
            text, calls = await ask_ai_tools(history, SUPPORT_TOOLS)
    except AIError:
        if not last:
            raise
        text, calls = "", []  # limitga yetgan suhbat AI xatosi tufayli osilib qolmasin: summary o'zimizdan

    lang = detect_lang(next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""))
    if text:
        await _send(bot, chat["user_id"], text)
        await add_support_message(chat["id"], "assistant", text)

    escalate = next((a for n, a in calls if n == "escalate_to_admin"), None)
    resolved = any(n == "resolve" for n, _ in calls)
    if escalate is None and last and not resolved:
        escalate = {}  # oxirgi navbatda AI hal qilmadi va qaror ham bermadi: baribir adminga
    if escalate is not None:
        summary = str(escalate.get("summary") or "").strip() or _fallback_summary(messages)
        await _escalate(bot, chat, summary, lang)
    elif resolved:
        await set_support_status(chat["id"], "active", "resolved")


async def open_chat(bot: Bot, message: Message, text: str, reason: str = "") -> None:
    """Guruhda AI contact_admin chaqirdi: foydalanuvchining lichkasida suhbat boshlanadi (guruhda javob yozilmaydi)."""
    user = message.from_user
    if user is None:
        return
    chat = await get_support_chat(user.id, "active", SUPPORT_TTL_HOURS)
    if chat is None:
        await create_support_chat(user.id, message.chat.id, message.chat.title, user.full_name, user.username, "active")
        chat = await get_support_chat(user.id, "active", SUPPORT_TTL_HOURS)
        if chat is None:
            return
    content = f"{GROUP_PREFIX} {text[:MAX_TEXT]}"
    if reason:
        content += f"\n[AI taxmini: {reason[:300]}]"
    await add_support_message(chat["id"], "user", content)

    async with _locks[user.id]:
        try:
            # AI'ga murojaatdan oldin: lichkaga yozib bo'ladimi (foydalanuvchi botga /start bosganmi)
            await bot.send_chat_action(user.id, ChatAction.TYPING)
            await run_turn(bot, chat)
            return
        except (TelegramForbiddenError, TelegramBadRequest):
            await set_support_status(chat["id"], "active", "awaiting_start")
    me = await bot.me()
    lang = detect_lang(text)
    await message.reply(texts.SUPPORT_START_FIRST[lang].format(link=f"https://t.me/{me.username}?start=support"))


async def resume_support(bot: Bot, user_id: int) -> None:
    """/start bosilganda: kutib turgan so'rov bo'lsa, suhbatni boshlaydi."""
    chat = await get_support_chat(user_id, "awaiting_start", SUPPORT_TTL_HOURS)
    if chat is None or not await set_support_status(chat["id"], "awaiting_start", "active"):
        return
    async with _locks[user_id]:
        await run_turn(bot, chat)


async def _chat_in(status: str, message: Message) -> dict | bool:
    if message.from_user is None:
        return False
    chat = await get_support_chat(message.from_user.id, status, SUPPORT_TTL_HOURS)
    return {"chat": chat} if chat else False


async def _active_chat(message: Message) -> dict | bool:
    return await _chat_in("active", message)


async def _escalated_chat(message: Message) -> dict | bool:
    return await _chat_in("escalated", message)


@router.message(F.text, ~F.text.startswith("/"), StateFilter(None), _active_chat)
async def on_support_message(message: Message, bot: Bot, chat: dict):
    if message.from_user is None or message.text is None:
        return
    async with _locks[message.from_user.id]:
        await add_support_message(chat["id"], "user", message.text.strip()[:MAX_TEXT])
        try:
            await run_turn(bot, chat)
        except AIError:
            await message.answer(texts.AI_ERROR[detect_lang(message.text)])
            raise


@router.message(F.text, ~F.text.startswith("/"), StateFilter(None), _escalated_chat)
async def on_after_escalation(message: Message, chat: dict):
    """Uzatilgan suhbatda bot AI'ga yubormaydi: admin o'zi gaplashadi; takroriy xabarlarga kamdan-kam eslatadi."""
    if message.from_user is None or message.text is None:
        return
    now = time.monotonic()
    if now - _last_wait.get(message.from_user.id, -WAIT_NOTICE_INTERVAL) < WAIT_NOTICE_INTERVAL:
        return
    if len(_last_wait) >= _LAST_WAIT_MAX:
        for uid in [u for u, t in _last_wait.items() if now - t >= WAIT_NOTICE_INTERVAL]:
            del _last_wait[uid]
    _last_wait[message.from_user.id] = now
    await message.answer(texts.SUPPORT_WAIT[detect_lang(message.text)])
