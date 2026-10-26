import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import VOTE_ACCEPT_PERCENT
from database import change_status, count_votes, get_due_votings, get_no_votes
from texts import APPLICATION_ACCEPTED, APPLICATION_REJECTED, FEEDBACK_INTRO
from utils.admin import safe_send
from utils.summary import feedback_for_applicant

logger = logging.getLogger(__name__)


def is_accepted(yes: int, no: int) -> bool:
    """Ovozlarning kamida VOTE_ACCEPT_PERCENT foizi "ha" bo'lsa, a'zo qabul qilinadi."""
    total = yes + no
    return total > 0 and yes * 100 >= VOTE_ACCEPT_PERCENT * total


async def finalize_due_votings(bot: Bot) -> int:
    """Muddati tugagan ovoz berishlarni yakunlaydi: adminlarsiz, faqat ovoz natijasi bo'yicha.

    Hech kim ovoz bermagan bo'lsa ariza yopiladi (expired). Aks holda "ha" ovozlari kamida
    VOTE_ACCEPT_PERCENT foiz bo'lsa so'rov tasdiqlanadi, bo'lmasa rad etiladi; rad etilganda "yo'q"
    ovoz bergan a'zolarning sabablari AI orqali umumiy xulosaga aylanib arizachiga yuboriladi.
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
        elif is_accepted(yes, no):
            new, result, note = "accepted", "✅ Qabul qilindi", APPLICATION_ACCEPTED
        else:
            new, result, note = "rejected", "❌ Rad etildi", APPLICATION_REJECTED

        # ayni paytda holat o'zgargan bo'lsa, change_status False qaytaradi
        if not await change_status(app["id"], old="voting", new=new):
            continue

        if new == "rejected":
            # a'zolar yozgan sabablar AI orqali yumshoq umumiy xulosaga aylanib, arizachiga yuboriladi
            reasons = [v["reason"] for v in await get_no_votes(app["id"])]
            feedback = await feedback_for_applicant(reasons)
            if feedback:
                note = f"{APPLICATION_REJECTED}\n\n{FEEDBACK_INTRO}\n{feedback}"

        done += 1
        logger.info("Ovoz berish yakunlandi: ariza %s -> %s (%s/%s)", app["id"], new, yes, no)

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
