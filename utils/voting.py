import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from database import change_status, count_votes, get_due_votings, get_no_votes
from keyboards.creator import creator_inline
from utils.admin import get_group_creator_id, safe_send

logger = logging.getLogger(__name__)

# creatorga boradigan xabar Telegram limiti (4096) ichida qolishi uchun
REPORT_LIMIT = 3500
REASON_LIMIT = 200


async def _voter_name(bot: Bot, group_id: int, voter_id: int) -> str:
    try:
        member = await bot.get_chat_member(group_id, voter_id)
        return member.user.full_name
    except TelegramAPIError:
        return str(voter_id)


async def _send_to_creator(bot: Bot, app: dict, yes: int, no: int) -> bool:
    """Creatorga 👎 ovozlar hisoboti va qaror tugmalarini yuboradi; yetkazilsa True."""
    creator_id = await get_group_creator_id(bot, app["group_id"])
    if creator_id is None:
        return False

    text = (
        "⚖️ <b>Oxirgi qaror sizda</b>\n\n"
        f"{app['anketa']}\n\n"
        f"Guruh ovozi: <b>{yes}</b> 👍 / <b>{no}</b> 👎\n"
        "👎 bergan a'zolar:"
    )
    no_votes = await get_no_votes(app["id"])
    shown = 0
    for v in no_votes:
        name = escape(await _voter_name(bot, app["group_id"], v["voter_id"]))
        reason = escape(v["reason"][:REASON_LIMIT]) if v["reason"] else "sabab yozilmagan"
        line = f"\n• <b>{name}</b>: {reason}"
        if len(text) + len(line) > REPORT_LIMIT:
            break
        text += line
        shown += 1
    if shown < len(no_votes):
        text += f"\n… va yana {len(no_votes) - shown} ta"
    text += "\n\nQabul qilasizmi yoki rad qilasizmi?"

    return await safe_send(
        bot=bot, chat_id=creator_id, text=text, reply_markup=creator_inline(app["id"])
    )


async def finalize_due_votings(bot: Bot) -> int:
    """Muddati tugagan ovoz berishlarni yakunlaydi.

    👍 ko'p bo'lsa qabul qilinadi. 👎 ko'p yoki teng bo'lsa qaror guruh creatoriga ketadi
    (handlers/creator.py). Hech kim ovoz bermagan bo'lsa ariza yopiladi.
    """
    done = 0
    for app in await get_due_votings():
        yes, no = await count_votes(app["id"])
        if yes == 0 and no == 0:
            new, result = "expired", "⌛ Ovoz berish muddati tugadi, hech kim ovoz bermadi."
            note = "Arizangiz bo'yicha hech kim ovoz bermadi va yopildi. Xohlasangiz, qayta so'rov yuborishingiz mumkin."
        elif yes > no:
            new, result = "accepted", "✅ Qabul qilindi"
            note = "Tabriklaymiz, arizangiz qabul qilindi! 🎉"
        else:
            new, result = "creator_review", "🔎 Creator qaroriga yuborildi"
            note = "Guruh a'zolarining ovozi tugadi. Oxirgi qarorni guruh egasi qabul qiladi, natijani kuting ⏳"

        # ayni paytda holat o'zgargan bo'lsa, change_status False qaytaradi
        if not await change_status(app["id"], old="voting", new=new):
            continue
        done += 1

        if new == "creator_review" and not await _send_to_creator(bot, app, yes, no):
            # creatorga yetkazib bo'lmasa (/start bosmagan), ariza osilib qolmasligi uchun rad etiladi
            logger.warning("Ariza %s: creatorga yuborib bo'lmadi, rad etildi", app["id"])
            await change_status(app["id"], old="creator_review", new="rejected")
            new, result = "rejected", "❌ Rad etildi"
            note = "Afsuski, guruh a'zolari arizangizni rad etishdi."
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

        await safe_send(bot=bot, chat_id=app["user_id"], text=note)
    return done
