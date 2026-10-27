import asyncio
import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)

from config import ADMIN_IDS, VOTE_ACCEPT_PERCENT
from database import change_status, count_votes, get_due_votings, get_no_votes
from keyboards.creator import creator_inline
from texts import (
    APPLICATION_ACCEPTED,
    APPLICATION_REJECTED,
    FEEDBACK_INTRO,
)
from utils.admin import notify_admins, safe_send, status_text
from utils.summary import feedback_for_applicant

logger = logging.getLogger(__name__)

SENT, UNREACHABLE, RETRY = "sent", "unreachable", "retry"


def _share_at_least(count: int, total: int) -> bool:
    return total > 0 and count * 100 >= VOTE_ACCEPT_PERCENT * total


def is_accepted(yes: int, no: int) -> bool:
    """Ovozlarning kamida VOTE_ACCEPT_PERCENT foizi "ha" bo'lsa, a'zo avtomatik qabul qilinadi."""
    # yes > no: VOTE_ACCEPT_PERCENT <= 50 bo'lsa ham "yo'q" ko'pchilik bo'lganda qabul qilinmaydi
    return yes > no and _share_at_least(yes, yes + no)


def is_rejected(yes: int, no: int) -> bool:
    """Ovozlarning kamida VOTE_ACCEPT_PERCENT foizi "yo'q" bo'lsa, ariza avtomatik rad etiladi."""
    return no > yes and _share_at_least(no, yes + no)


async def rejection_note(app_id: int) -> str:
    """Rad etilgan arizachiga xabar: "yo'q" deganlarning sabablari AI orqali yumshoq umumiy xulosaga aylanadi.

    Sabab yozilmagan yoki AI ishlamasa, faqat oddiy rad matni (xom sabablar hech qachon yuborilmaydi).
    """
    reasons = [v["reason"] for v in await get_no_votes(app_id)]
    feedback = await feedback_for_applicant(reasons)
    if feedback:
        return f"{APPLICATION_REJECTED}\n\n{FEEDBACK_INTRO}\n{feedback}"
    return APPLICATION_REJECTED


def report_text(app: dict) -> str:
    """Adminlarga boradigan xabar: faqat anketa (telefon bilan); qaror tugmalar orqali."""
    return f"{app['anketa']}" + (f"📞 <b>Telefon:</b> {escape(app['phone'])}\n" if app.get("phone") else "")


async def _send_one(bot: Bot, admin_id: int, text: str, app_id: int) -> str:
    try:
        await bot.send_message(chat_id=admin_id, text=text, reply_markup=creator_inline(app_id))
    except (TelegramBadRequest, TelegramForbiddenError):
        return UNREACHABLE
    except TelegramAPIError as e:
        logger.warning("Ariza %s: adminga (%s) yuborishda vaqtinchalik xato: %r", app_id, admin_id, e)
        return RETRY
    return SENT


async def _send_to_admins(bot: Bot, app: dict, yes: int, no: int) -> str:
    """Barcha adminlarga hisobot va Qabul/Rad tugmalarini yuboradi (👎 sabablari faqat confirm oynasida).

    SENT: kamida bitta adminga yetkazildi. UNREACHABLE: hech kimga yetkazib bo'lmaydi (/start bosmagan,
    bloklagan yoki ADMIN_IDS bo'sh). RETRY: yetkazilmadi va vaqtinchalik xato bor (flood limit, tarmoq):
    keyingi aylanishda qayta uriniladi.
    """
    if not ADMIN_IDS:
        return UNREACHABLE
    try:
        text = report_text(app)
        results = await asyncio.gather(*(_send_one(bot, a, text, app["id"]) for a in ADMIN_IDS))
    except Exception:
        logger.exception("Ariza %s: adminlar hisobotini tayyorlashda xatolik", app["id"])
        return RETRY
    if SENT in results:
        return SENT
    return RETRY if RETRY in results else UNREACHABLE


async def finalize_due_votings(bot: Bot) -> int:
    """Muddati tugagan ovoz berishlarni yakunlaydi.

    - hech kim ovoz bermagan: ariza yopiladi (expired)
    - "ha" kamida VOTE_ACCEPT_PERCENT %: avtomatik qabul
    - "yo'q" kamida VOTE_ACCEPT_PERCENT %: avtomatik rad (arizachiga AI xulosasi bilan)
    - ikkala tomon ham yetmasa: adminlarga hisobot, qaror ularda (handlers/creator.py);
      adminlarga yetkazib bo'lmasa, ko'pchilik ovoz hal qiladi.
    """
    due = await get_due_votings()
    # arizalar bir-biriga xalaqit bermasligi uchun parallel: bittasida sekin AI/tarmoq boshqalarni kutdirmasin
    results = await asyncio.gather(*(_finalize_one(bot, app) for app in due), return_exceptions=True)
    done = 0
    for app, res in zip(due, results):
        if isinstance(res, BaseException):
            logger.error("Ariza %s yakunlashda xatolik: %r", app["id"], res, exc_info=res)
        elif res:
            done += 1
    return done


async def _finalize_one(bot: Bot, app: dict) -> bool:
    """Bitta arizani yakunlaydi; False: hech narsa o'zgarmadi yoki keyingi aylanishga qoldi."""
    yes, no = await count_votes(app["id"])
    note: str | None = None
    if yes == 0 and no == 0:
        new, result = "expired", "⌛ Ovoz berish yakunlandi: hech kim ovoz bermadi, ariza yopildi."
        note = (
            "Arizangiz bo'yicha hech kim ovoz bermadi, shuning uchun u yopildi. "
            "Xohlasangiz, guruhga qo'shilish so'rovini qayta yuborishingiz mumkin."
        )
    elif is_accepted(yes, no):
        new, result, note = "accepted", "✅ Qabul qilindi", APPLICATION_ACCEPTED
    elif is_rejected(yes, no):
        new, result = "rejected", "❌ Rad etildi"
    else:
        new, result = "creator_review", "🔎 Yakuniy qaror adminlarga yuborildi"
        note = (
            "Guruh a'zolarining ovoz berishi yakunlandi. "
            "Yakuniy qarorni adminlar qabul qiladi, natijani shu yerda xabar qilamiz ⏳"
        )

    # ayni paytda holat o'zgargan bo'lsa, change_status False qaytaradi
    if not await change_status(app["id"], old="voting", new=new):
        return False

    if new == "creator_review":
        outcome = await _send_to_admins(bot, app, yes, no)
        if outcome == RETRY:
            # vaqtinchalik xato: ariza "voting" da qoladi (muddat tugagan, ovoz qabul qilinmaydi)
            # va keyingi aylanishda hisobot qayta yuboriladi
            await change_status(app["id"], old="creator_review", new="voting")
            return False
        if outcome == UNREACHABLE:
            # adminlarga yetkazib bo'lmasa (/start bosmagan), ariza osilib qolmasligi uchun
            # ko'pchilik ovoz hal qiladi (👍 ko'p bo'lsa qabul, aks holda rad)
            new = "accepted" if yes > no else "rejected"
            logger.warning(
                "Ariza %s: adminlarga yuborib bo'lmadi, ko'pchilik ovoz bo'yicha hal qilindi: %s",
                app["id"], new,
            )
            await change_status(app["id"], old="creator_review", new=new)
            if new == "accepted":
                result, note = "✅ Qabul qilindi", APPLICATION_ACCEPTED
            else:
                result, note = "❌ Rad etildi", None

    logger.info("Ovoz berish yakunlandi: ariza %s -> %s (%s/%s)", app["id"], new, yes, no)

    if new in ("accepted", "rejected", "expired"):
        try:
            if new == "accepted":
                await bot.approve_chat_join_request(chat_id=app["group_id"], user_id=app["user_id"])
            else:
                await bot.decline_chat_join_request(chat_id=app["group_id"], user_id=app["user_id"])
        except TelegramAPIError:
            pass  # so'rov muddati o'tgan yoki foydalanuvchi allaqachon a'zo

    if app["vote_message_id"]:
        try:
            await bot.delete_message(
                chat_id=app["group_id"], message_id=app["vote_message_id"]
            )
        except TelegramAPIError:
            # o'chirib bo'lmasa (xabar allaqachon o'chgan yoki huquq yo'q), natijani xabarga yozamiz
            try:
                await bot.edit_message_text(
                    chat_id=app["group_id"],
                    message_id=app["vote_message_id"],
                    text=f"{app['anketa']}\n\n{result}",
                )
            except TelegramAPIError:
                pass

    # adminlarga natija statusi: "Ism Familiya guruhga qabul qilindi/qilinmadi" (qaror adminlarda bo'lsa, undan keyin)
    if new == "accepted":
        await notify_admins(bot, status_text(app, True))
    elif new == "rejected":
        await notify_admins(bot, status_text(app, False))
    elif new == "expired":
        await notify_admins(bot, status_text(app, False, ": hech kim ovoz bermadi"))

    # AI xulosasi eng oxirida: guruhdagi ish (so'rov, xabarni o'chirish) AI kutishiga bog'liq emas
    if new == "rejected":
        note = await rejection_note(app["id"])

    try:
        await safe_send(bot=bot, chat_id=app["user_id"], text=note)
    except TelegramAPIError:
        # flood limit/tarmoq: holat allaqachon yozilgan, qolgan arizalar to'xtab qolmasin
        logger.warning("Ariza %s: foydalanuvchiga xabar yuborib bo'lmadi", app["id"])
    return True
