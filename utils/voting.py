import asyncio
import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)

from database import (
    change_status,
    count_votes,
    get_due_votings,
)
from config import ADMIN_IDS
from keyboards.creator import creator_inline
from texts import APPLICATION_ACCEPTED, APPLICATION_REJECTED
from utils.admin import safe_send

logger = logging.getLogger(__name__)

SENT, UNREACHABLE, RETRY = "sent", "unreachable", "retry"


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
    """Barcha adminlarga anketa, 👍/👎 soni va qaror tugmalarini yuboradi (👎 sabablari bu yerda yo'q).

    SENT: kamida bitta adminga yetkazildi. UNREACHABLE: hech kimga yetkazib bo'lmaydi (/start bosmagan,
    bloklagan yoki ADMIN_IDS bo'sh). RETRY: yetkazilmadi va vaqtinchalik xato bor (flood limit, tarmoq):
    keyingi aylanishda qayta uriniladi.
    """
    if not ADMIN_IDS:
        return UNREACHABLE
    try:
        text = (
            "⚖️ <b>Ovoz berish yakunlandi</b>\n\n"
            f"{app['anketa']}"
            + (f"📞 <b>Telefon:</b> {escape(app['phone'])}\n" if app.get("phone") else "")
            + "\n"
            f"Ovozlar: <b>{yes}</b> 👍 / <b>{no}</b> 👎\n\n"
            "Arizani qabul qilasizmi yoki rad etasizmi? Qarorni istalgan admin qabul qiladi."
        )
        results = await asyncio.gather(*(_send_one(bot, a, text, app["id"]) for a in ADMIN_IDS))
    except Exception:
        logger.exception("Ariza %s: adminlar hisobotini tayyorlashda xatolik", app["id"])
        return RETRY
    if SENT in results:
        return SENT
    return RETRY if RETRY in results else UNREACHABLE


async def finalize_due_votings(bot: Bot) -> int:
    """Muddati tugagan ovoz berishlarni yakunlaydi.

    Kamida bitta ovoz bo'lsa, natijadan qat'i nazar qaror adminlarga ketadi (handlers/creator.py);
    adminlarga yetkazib bo'lmasa guruh ovozi hal qiladi. Hech kim ovoz bermagan bo'lsa ariza yopiladi.
    """
    done = 0
    for app in await get_due_votings():
        yes, no = await count_votes(app["id"])
        if yes == 0 and no == 0:
            new, result = "expired", "⌛ Ovoz berish yakunlandi: hech kim ovoz bermadi, ariza yopildi."
            note = (
                "Arizangiz bo'yicha hech kim ovoz bermadi, shuning uchun u yopildi. "
                "Xohlasangiz, guruhga qo'shilish so'rovini qayta yuborishingiz mumkin."
            )
        else:
            # ovoz natijasidan qat'i nazar (👍 ko'p bo'lsa ham) oxirgi qarorni adminlar qabul qiladi
            new, result = "creator_review", "🔎 Yakuniy qaror adminlarga yuborildi"
            note = (
                "Guruh a'zolarining ovoz berishi yakunlandi. "
                "Yakuniy qarorni adminlar qabul qiladi, natijani shu yerda xabar qilamiz ⏳"
            )

        # ayni paytda holat o'zgargan bo'lsa, change_status False qaytaradi
        if not await change_status(app["id"], old="voting", new=new):
            continue

        if new == "creator_review":
            outcome = await _send_to_admins(bot, app, yes, no)
            if outcome == RETRY:
                # vaqtinchalik xato: ariza "voting" da qoladi (muddat tugagan, ovoz qabul qilinmaydi)
                # va keyingi aylanishda hisobot qayta yuboriladi
                await change_status(app["id"], old="creator_review", new="voting")
                continue
            if outcome == UNREACHABLE:
                # adminlarga yetkazib bo'lmasa (/start bosmagan), ariza osilib qolmasligi uchun
                # guruh ovozi bo'yicha hal qilinadi (👍 ko'p bo'lsa qabul, aks holda rad)
                new = "accepted" if yes > no else "rejected"
                logger.warning(
                    "Ariza %s: adminlarga yuborib bo'lmadi, ovoz bo'yicha hal qilindi: %s", app["id"], new
                )
                await change_status(app["id"], old="creator_review", new=new)
                if new == "accepted":
                    result, note = "✅ Qabul qilindi", APPLICATION_ACCEPTED
                else:
                    result, note = "❌ Rad etildi", APPLICATION_REJECTED
        done += 1
        logger.info("Ovoz berish yakunlandi: ariza %s -> %s (%s/%s)", app["id"], new, yes, no)

        if new != "creator_review":
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

        try:
            await safe_send(bot=bot, chat_id=app["user_id"], text=note)
        except TelegramAPIError:
            # flood limit/tarmoq: holat allaqachon yozilgan, qolgan arizalar to'xtab qolmasin
            logger.warning("Ariza %s: foydalanuvchiga xabar yuborib bo'lmadi", app["id"])
    return done
