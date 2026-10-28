import asyncio
import logging
from contextlib import suppress
import time
from collections import defaultdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

import texts
from config import ADMIN_IDS, SUPPORT_MAX_TURNS, SUPPORT_TTL_HOURS
from database import (
    get_pending_reason,
    add_support_message,
    add_support_warning,
    count_recent_escalations,
    create_support_chat,
    get_support_chat,
    get_support_messages,
    set_support_status,
    user_groups,
)
from utils.admin import is_admin, is_group_member, safe_send
from utils.autodelete import keep_messages, schedule_delete
from utils.ai import AIError, ask_ai, ask_ai_tools
from utils.ai_html import plain_text, sanitize_html
from utils.lang import detect_lang
from utils import content_check
from utils.ads import AD, DANGER
from utils.profanity import has_profanity
from utils.support_policy import (
    BLOCKING_CATEGORIES,
    wants_admin,
    DECLINE_CATEGORIES,
    DECLINE_COOLDOWN_HOURS,
    FORWARD_CATEGORIES,
    MAX_ESCALATIONS_PER_DAY,
)

router = Router()
router.message.filter(F.chat.type == "private")
logger = logging.getLogger(__name__)

MAX_TEXT = 2000
GROUP_PREFIX = "[Guruhdagi xabar]"
WAIT_NOTICE_INTERVAL = 60
IDLE_NOTICE_INTERVAL = 10  # suhbati yo'q foydalanuvchiga: qisqa, aks holda bot "o'lib qolgandek" ko'rinadi

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
                "summary": {
                    "type": "string",
                    "description": "Calm, factual summary for the admin, in Uzbek: who wants what and all details. "
                    "No insults or sensitive data.",
                },
                "category": {"type": "string", "enum": list(FORWARD_CATEGORIES), "description": "Kind of the matter."},
            },
            "required": ["summary", "category"],
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
DECLINE_TOOL = {
    "type": "function",
    "function": {
        "name": "decline",
        "description": (
            "The matter must NOT reach the admins (prohibited advertising, abuse, immoral offers, scam, spam, no stated "
            "purpose, or still unclear). Write a short polite refusal as the reply text."
        ),
        "parameters": {
            "type": "object",
            "properties": {"category": {"type": "string", "enum": list(DECLINE_CATEGORIES)}},
            "required": ["category"],
        },
    },
}
SUPPORT_TOOLS = [ESCALATE_TOOL, DECLINE_TOOL, RESOLVE_TOOL]

# bir foydalanuvchining xabarlari ketma-ket ishlansin (AI javobi kelguncha yana yozsa, suhbat chalkashmasin)
_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_last_wait: dict[int, float] = {}
_last_idle: dict[int, float] = {}
_LAST_WAIT_MAX = 1000


def _throttled(store: dict[int, float], user_id: int, interval: float = WAIT_NOTICE_INTERVAL) -> bool:
    """Bir foydalanuvchiga avtomatik eslatma `interval` soniyada ko'pi bilan bir marta (takroriy xabarlarga javob yog'ilmasin)."""
    now = time.monotonic()
    if now - store.get(user_id, -interval) < interval:
        return True
    if len(store) >= _LAST_WAIT_MAX:
        for uid in [u for u, t in store.items() if now - t >= interval]:
            del store[uid]
    store[user_id] = now
    return False


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


async def _escalate(chat: dict, category: str) -> str | None:
    """Uzatishni rasmiylashtiradi (holat "escalated"); natija: "escalated" | "limit" (None: allaqachon uzatilgan/yopilgan).

    Adminlarga yuborish keyin, foydalanuvchi "yetkazildi" xabarini o'qigach: `_deliver`.
    """
    if await count_recent_escalations(chat["user_id"], 24) >= MAX_ESCALATIONS_PER_DAY:
        return "limit" if await set_support_status(chat["id"], "active", "declined", "limit") else None
    return "escalated" if await set_support_status(chat["id"], "active", "escalated", category) else None


async def _deliver(bot: Bot, chat: dict, summary: str, lang: str) -> None:
    """Xulosani adminlarga yuboradi (foydalanuvchiga "yetkazildi" deyilgandan KEYIN); hech kimga yetmasa, foydalanuvchiga aytadi."""
    if await _notify_admins(bot, chat, summary) > 0:
        return
    logger.error("Support so'rovi hech bir adminga yetmadi (chat_id=%s, ADMIN_IDS=%s)", chat["id"], len(ADMIN_IDS))
    await set_support_status(chat["id"], "escalated", "active")  # suhbat qayta ochiladi
    await safe_send(bot, chat["user_id"], texts.SUPPORT_ADMIN_UNAVAILABLE[lang])


async def _decline(chat: dict, category: str, close: bool) -> bool:
    """Masala adminga yetkazilmaydi; turi bazada saqlanadi (AI xatosini keyin ko'rish uchun).

    close=False: suhbat davom etadi (foydalanuvchi boshqa masala aytishi mumkin); close=True (limit, haqorat): yopiladi.
    """
    if not await set_support_status(chat["id"], "active", "declined" if close else "active", category):
        return False
    logger.info("Support so'rovi adminga yetkazilmadi (chat_id=%s, kategoriya=%s, yopildi=%s)", chat["id"], category, close)
    return True


async def _say(bot: Bot, chat: dict, history: list[dict], outcome: str, fallback: dict[str, str], lang: str) -> None:
    """Qaror bajarilgach AI yakuniy javobni natijadan xabardor holda o'zi yozadi: matn har doim bajarilgan ish bilan mos.

    AI yoza olmasa, tayyor zaxira matn yuboriladi.
    """
    try:
        text = await ask_ai([*history, {"role": "system", "content": outcome}])
    except AIError as e:
        logger.warning("Support yakuniy javobini AI yozmadi, zaxira matn yuborildi: %r", e)
        await safe_send(bot, chat["user_id"], fallback[lang])
        return
    try:
        await _send(bot, chat["user_id"], text)
    except (TelegramForbiddenError, TelegramBadRequest):
        return
    await add_support_message(chat["id"], "assistant", text)


# bot tekshiruvi topgan qoidabuzarlik -> (foydalanuvchiga ogohlantirish, suhbat yopilsa saqlanadigan tur)
_VIOLATIONS = {
    "abuse": (texts.SUPPORT_REPHRASE, "abuse"),
    DANGER: (texts.SUPPORT_LINK_DANGER, "violation"),
    content_check.NSFW: (texts.SUPPORT_NSFW, "violation"),
}
AD_NOTE = "[Bot tekshiruvi: reklama belgilari bor]"


async def _strike(bot: Bot, chat: dict, kind: str, lang: str) -> None:
    """Qoidabuzarlik: birinchisiga ogohlantirish, takrorlansa suhbat yopiladi va foydalanuvchiga aytiladi."""
    warning, category = _VIOLATIONS[kind]
    if await add_support_warning(chat["id"]) == 1:
        await safe_send(bot, chat["user_id"], warning[lang])
    elif await _decline(chat, category, close=True):
        await safe_send(bot, chat["user_id"], texts.SUPPORT_CLOSED[lang].format(hours=DECLINE_COOLDOWN_HOURS))


async def _accept(bot: Bot, chat: dict, message: Message) -> str | None:
    """Lichkadagi xabar guruhdagi tekshiruvlarning o'zidan o'tadi (utils/content_check): 18+ media, xavfli havola,
    reklama, rasmdagi yozuv va QR-kod; keyin odobsiz so'zlar. Qabul qilinsa, suhbat tarixiga yoziladigan tavsif
    (matn bo'lmagan xabar ham: "[rasm] ..."), aks holda None (tarixga ham, adminga xulosaga ham kirmaydi)."""
    inspection = await content_check.inspect(bot, message, group_id=chat["group_id"])
    lang = detect_lang(inspection.text)
    if inspection.verdict in (DANGER, content_check.NSFW):
        await _strike(bot, chat, inspection.verdict, lang)
        return None
    if has_profanity(inspection.text):  # AI'siz; qo'pol, lekin so'kinishsiz matnni support AI o'zi rad etadi
        await _strike(bot, chat, "abuse", lang)
        return None
    content = content_check.describe(message, inspection.text)[:MAX_TEXT]
    if inspection.verdict == AD:
        # lichkada reklama o'chirilmaydi: ruxsat etilganmi yoki taqiqlanganmi, support AI qoidalari bo'yicha hal qiladi
        content += f"\n{AD_NOTE}"
    return content or None


async def run_turn(bot: Bot, chat: dict) -> None:
    """Saqlangan suhbat bo'yicha AI javobi: matnni foydalanuvchiga yuboradi, tool chaqirsa bajaradi."""
    messages = await get_support_messages(chat["id"])
    # limit lichkadagi xabarlarga: guruhdan ko'chirilgan birinchi xabar hisobga kirmaydi
    user_turns = sum(m["role"] == "user" and not m["content"].startswith(GROUP_PREFIX) for m in messages)
    last = user_turns >= SUPPORT_MAX_TURNS
    history = [{"role": "system", "content": texts.SUPPORT_SYSTEM_PROMPT}, *messages]
    tools = SUPPORT_TOOLS
    if last:
        # limitga yetdi: adminga hech narsa bormaydi, AI faqat hal qiladi (resolve) yoki rad etadi (decline)
        history.append({"role": "system", "content": texts.SUPPORT_LAST_TURN})
        tools = [DECLINE_TOOL, RESOLVE_TOOL]
    else:
        # limit — yuqori chegara, maqsad emas: AI masala aniq bo'lishi bilan qaror qiladi
        history.append(
            {"role": "system", "content": texts.SUPPORT_TURN_BUDGET.format(n=max(user_turns, 1), limit=SUPPORT_MAX_TURNS)}
        )

    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat["user_id"]):
            text, calls = await ask_ai_tools(history, tools)
    except AIError:
        if not last:
            raise
        text, calls = "", []  # limitga yetgan suhbat AI xatosi tufayli osilib qolmasin: yopiladi

    lang = detect_lang(next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""))
    decline = next((a for n, a in calls if n == "decline"), None)
    escalate = next((a for n, a in calls if n == "escalate_to_admin"), None)
    resolved = any(n == "resolve" for n, _ in calls)
    implicit = last and not resolved and decline is None  # limitga yetdi va AI hal qilmadi, qaror ham bermadi
    if implicit:
        decline = {"category": "unclear"}

    if decline is not None:  # ikkalasi bo'lsa, xavfsizi: adminga yubormaymiz
        category = str(decline.get("category") or "")
        category = category if category in DECLINE_CATEGORIES else "unclear"
        if not await _decline(chat, category, close=last):
            return
        if last:
            # suhbat yopildi: foydalanuvchi buni albatta bilishi kerak (AI yakuniy javobi yoki tayyor matn)
            await _say(bot, chat, history, texts.SUPPORT_OUTCOME_CLOSED, texts.SUPPORT_TURNS_CLOSED, lang)
            return
        outcome = texts.SUPPORT_OUTCOME_DECLINED
        fallback = texts.SUPPORT_DECLINED_BY_CATEGORY.get(category, texts.SUPPORT_DECLINED)
        await _say(bot, chat, history, outcome, fallback, lang)
        return
    if escalate is not None:
        summary = str(escalate.get("summary") or "").strip() or _fallback_summary(messages)
        category = str(escalate.get("category") or "")
        result = await _escalate(chat, category if category in FORWARD_CATEGORIES else "other")
        if result is None:
            return
        outcome, fallback = {
            "escalated": (texts.SUPPORT_OUTCOME_ESCALATED, texts.SUPPORT_ESCALATED),
            "limit": (texts.SUPPORT_OUTCOME_LIMIT, texts.SUPPORT_LIMIT),
        }[result]
        await _say(bot, chat, history, outcome, fallback, lang)  # AI matni emas, natijadan xabardor yangi javob
        if result == "escalated":
            await _deliver(bot, chat, summary, lang)  # avval foydalanuvchi "yetkazildi" deb o'qiydi, keyin admin oladi
        return

    if text:
        await _send(bot, chat["user_id"], text)
        await add_support_message(chat["id"], "assistant", text)
    if resolved:
        await set_support_status(chat["id"], "active", "resolved")


async def _reply_in_group(bot: Bot, message: Message, text: str, *, keep: bool = False) -> None:
    """Guruhga qisqa javob. keep=True: javob ham, foydalanuvchi xabari ham qoladi; aks holda ikkalasi AUTO_DELETE_SECONDS dan keyin o'chadi."""
    with suppress(TelegramAPIError):  # xabar o'chirilgan bo'lsa ham, lichkaga yuborilgan suhbat buzilmasin
        if keep:
            with keep_messages():
                await message.reply(text)
        else:
            await message.reply(text)
    if not keep:
        await schedule_delete(bot, message.chat.id, message.message_id)


def _blocked_notice(chat: dict, lang: str) -> str:
    """Yopilgan suhbat haqida: kunlik limit yoki qoidabuzarlik (va qachon qayta yozish mumkinligi)."""
    if chat.get("category") == "limit":
        return texts.SUPPORT_LIMIT[lang]
    return texts.SUPPORT_CLOSED[lang].format(hours=DECLINE_COOLDOWN_HOURS)


async def open_chat(bot: Bot, message: Message, text: str, reason: str = "") -> None:
    """Guruhda AI contact_admin chaqirdi: foydalanuvchining lichkasida suhbat boshlanadi (guruhda javob yozilmaydi)."""
    user = message.from_user
    if user is None:
        return
    blocked = await get_support_chat(user.id, "declined", DECLINE_COOLDOWN_HOURS, BLOCKING_CATEGORIES)
    if blocked is not None:
        # qoidabuzarlik yoki kunlik limit tufayli yopilgan: AI'siz, nega yopilgani aytiladi
        logger.info("Support: foydalanuvchi bloklangan (chat_id=%s, kategoriya=%s), AI chaqirilmadi", blocked["id"], blocked["category"])
        lang = detect_lang(text)
        if await safe_send(bot, user.id, _blocked_notice(blocked, lang)):
            await _reply_in_group(bot, message, texts.SUPPORT_DM_SENT[lang], keep=True)
        return
    chat = await get_support_chat(user.id, "active", SUPPORT_TTL_HOURS)
    if chat is None:
        await create_support_chat(user.id, message.chat.id, message.chat.title, user.full_name, user.username, "active")
        chat = await get_support_chat(user.id, "active", SUPPORT_TTL_HOURS)
        if chat is None:
            return
    if has_profanity(text):
        content = f"{GROUP_PREFIX} (odobsiz matn olib tashlandi)"  # na adminga, na AI xulosasiga o'tmaydi
    else:
        content = f"{GROUP_PREFIX} {text[:MAX_TEXT]}"
        if reason:
            content += f"\n[AI taxmini: {reason[:300]}]"
    await add_support_message(chat["id"], "user", content)

    async with _locks[user.id]:
        try:
            # AI'ga murojaatdan oldin: lichkaga yozib bo'ladimi (foydalanuvchi botga /start bosganmi)
            await bot.send_chat_action(user.id, ChatAction.TYPING)
            await run_turn(bot, chat)
        except (TelegramForbiddenError, TelegramBadRequest):
            await set_support_status(chat["id"], "active", "awaiting_start")
        else:
            # guruhdagi "yozmoqda..." kimga ekani noma'lum: qisqa xabar (guruh xabarlari kabi o'zi o'chadi)
            await _reply_in_group(bot, message, texts.SUPPORT_DM_SENT[detect_lang(text)], keep=True)
            return
    me = await bot.me()
    lang = detect_lang(text)
    await _reply_in_group(bot, message, texts.SUPPORT_START_FIRST[lang].format(link=f"https://t.me/{me.username}?start=support"))


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


def _not_command(message: Message) -> bool:
    """Har qanday xabar (matn, rasm, ovoz, fayl...), faqat "/" buyrug'i emas."""
    return not (message.text or "").startswith("/")


@router.message(_not_command, StateFilter(None), _active_chat)
async def on_support_message(message: Message, bot: Bot, chat: dict):
    if message.from_user is None:
        return
    async with _locks[message.from_user.id]:
        content = await _accept(bot, chat, message)
        if content is None:
            return
        await add_support_message(chat["id"], "user", content)
        try:
            await run_turn(bot, chat)
        except AIError:
            await message.answer(texts.AI_ERROR[detect_lang(content)])
            raise


@router.message(_not_command, StateFilter(None), _escalated_chat)
async def on_after_escalation(message: Message, chat: dict):
    """Uzatilgan suhbatda bot AI'ga yubormaydi: admin o'zi gaplashadi; takroriy xabarlarga kamdan-kam eslatadi."""
    if message.from_user is None:
        return
    if _throttled(_last_wait, message.from_user.id):
        return
    await message.answer(texts.SUPPORT_WAIT[detect_lang(message.text or message.caption or "")])


async def _idle_user(message: Message) -> bool:
    """Faol suhbati yo'q oddiy foydalanuvchi (adminlar va "yo'q" ovoz sababini yozayotganlar bundan mustasno)."""
    user = message.from_user
    return user is not None and not is_admin(user.id) and await get_pending_reason(user.id) is None


async def _member_group(bot: Bot, user_id: int) -> int | None:
    """Foydalanuvchi hozir a'zo bo'lgan guruh (bot biladigan guruhlardan, Telegram'da tekshirib)."""
    for group_id in await user_groups(user_id):
        if await is_group_member(bot, group_id, user_id):
            return group_id
    return None


@router.message(_not_command, StateFilter(None), _idle_user)
async def on_idle_message(message: Message, bot: Bot):
    """Suhbati yo'q foydalanuvchi lichkaga yozdi. Admin bilan gaplashmoqchi ekani aniq bo'lsa (`wants_admin`, AI'siz)
    va guruh a'zosi bo'lsa, guruhda botni belgilamasa ham admin suhbati shu yerda boshlanadi. Boshqa har qanday xabarga
    AI chaqirilmaydi: qisqa yo'l-yo'riq (yoki bloklangan bo'lsa, nega)."""
    user = message.from_user
    if user is None:
        return
    lang = detect_lang(message.text or message.caption or "")
    blocked = await get_support_chat(user.id, "declined", DECLINE_COOLDOWN_HOURS, BLOCKING_CATEGORIES)
    if blocked is not None:
        if not _throttled(_last_idle, user.id, IDLE_NOTICE_INTERVAL):
            await message.answer(_blocked_notice(blocked, lang))
        return
    if not wants_admin(message.text or message.caption or ""):
        if not _throttled(_last_idle, user.id, IDLE_NOTICE_INTERVAL):
            await message.answer(texts.SUPPORT_HOWTO[lang])
        return
    group_id = await _member_group(bot, user.id)
    if group_id is None:
        if not _throttled(_last_idle, user.id, IDLE_NOTICE_INTERVAL):
            await message.answer(texts.SUPPORT_IDLE[lang])
        return
    async with _locks[user.id]:
        chat = await get_support_chat(user.id, "active", SUPPORT_TTL_HOURS)
        if chat is None:
            await create_support_chat(user.id, group_id, None, user.full_name, user.username, "active")
            chat = await get_support_chat(user.id, "active", SUPPORT_TTL_HOURS)
            if chat is None:
                return
        content = await _accept(bot, chat, message)
        if content is None:
            return
        await add_support_message(chat["id"], "user", content)
        try:
            await run_turn(bot, chat)
        except AIError:
            await message.answer(texts.AI_ERROR[lang])
            raise
