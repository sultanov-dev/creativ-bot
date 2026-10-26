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
from keyboards.creator import creator_inline
from texts import APPLICATION_ACCEPTED, APPLICATION_REJECTED
from utils.admin import get_group_creator_id, safe_send

logger = logging.getLogger(__name__)

HEADER = "@@HEADER@@"  # creator va adminlar uchun sarlavha almashtiriladi


SENT, UNREACHABLE, RETRY = "sent", "unreachable", "retry"


async def _send_to_creator(bot: Bot, app: dict, yes: int, no: int) -> str:
    """Creatorga anketa, 👍/👎 soni va qaror tugmalarini yuboradi (👎 sabablari bu yerda ko'rsatilmaydi).

    SENT: yetkazildi. UNREACHABLE: creatorga yetkazib bo'lmaydi (/start bosmagan, bloklagan).
    RETRY: vaqtinchalik xato (flood limit, tarmoq): keyingi aylanishda qayta uriniladi.
    """
    try:
        return await _send_report(bot, app, yes, no)
    except TelegramAPIError as e:
        logger.warning("Ariza %s: creatorga yuborishda vaqtinchalik xato: %r", app["id"], e)
        return RETRY
    except Exception:
        logger.exception("Ariza %s: creator hisobotini tayyorlashda xatolik", app["id"])
        return RETRY


async def _send_report(bot: Bot, app: dict, yes: int, no: int) -> str:
    creator_id = await get_group_creator_id(bot, app["group_id"])
    if creator_id is None:
        return UNREACHABLE

    text = (
        f"{HEADER}\n\n"
        f"{app['anketa']}"
        + (f"📞 <b>Telefon:</b> {escape(app['phone'])}\n" if app.get("phone") else "")
        + "\n"
        f"Ovozlar: <b>{yes}</b> 👍 / <b>{no}</b> 👎"
    )
    try:
        await bot.send_message(
            chat_id=creator_id,
            text=text.replace(HEADER, "⚖️ <b>Yakuniy qaror sizda</b>", 1)
            + "\n\nArizani qabul qilasizmi yoki rad etasizmi?",
            reply_markup=creator_inline(app["id"]),
        )
    except (TelegramBadRequest, TelegramForbiddenError):
        return UNREACHABLE

    # boshqa adminlarga faqat ma'lumot uchun nusxa (tugmalarsiz): qarorni baribir creator qabul qiladi
    info = text.replace(HEADER, "📋 <b>Ovoz berish yakunlandi</b>", 1) + (
        "\n\nYakuniy qarorni guruh egasi qabul qiladi."
    )
    try:
        admins = await bot.get_chat_administrators(app["group_id"])
    except TelegramAPIError:
        return SENT
    for a in admins:
        if a.user.is_bot or a.user.id == creator_id:
            continue
        await safe_send(bot=bot, chat_id=a.user.id, text=info)
    return SENT


async def finalize_due_votings(bot: Bot) -> int:
    """Muddati tugagan ovoz berishlarni yakunlaydi.

    Kamida bitta ovoz bo'lsa, natijadan qat'i nazar qaror guruh creatoriga ketadi (handlers/creator.py);
    creatorga yetkazib bo'lmasa guruh ovozi hal qiladi. Hech kim ovoz bermagan bo'lsa ariza yopiladi.
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
            # ovoz natijasidan qat'i nazar (👍 ko'p bo'lsa ham) oxirgi qarorni creator qabul qiladi
            new, result = "creator_review", "🔎 Yakuniy qaror guruh egasiga yuborildi"
            note = (
                "Guruh a'zolarining ovoz berishi yakunlandi. "
                "Yakuniy qarorni guruh egasi qabul qiladi, natijani shu yerda xabar qilamiz ⏳"
            )

        # ayni paytda holat o'zgargan bo'lsa, change_status False qaytaradi
        if not await change_status(app["id"], old="voting", new=new):
            continue

        if new == "creator_review":
            outcome = await _send_to_creator(bot, app, yes, no)
            if outcome == RETRY:
                # vaqtinchalik xato: ariza "voting" da qoladi (muddat tugagan, ovoz qabul qilinmaydi)
                # va keyingi aylanishda hisobot qayta yuboriladi
                await change_status(app["id"], old="creator_review", new="voting")
                continue
            if outcome == UNREACHABLE:
                # creatorga yetkazib bo'lmasa (/start bosmagan), ariza osilib qolmasligi uchun
                # guruh ovozi bo'yicha hal qilinadi (👍 ko'p bo'lsa qabul, aks holda rad)
                new = "accepted" if yes > no else "rejected"
                logger.warning(
                    "Ariza %s: creatorga yuborib bo'lmadi, ovoz bo'yicha hal qilindi: %s", app["id"], new
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
