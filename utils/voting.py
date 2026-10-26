import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from database import change_status, count_votes, get_due_votings
from utils.admin import safe_send

logger = logging.getLogger(__name__)


async def finalize_due_votings(bot: Bot) -> int:
    """Muddati tugagan ovoz berishlarni yakunlaydi: vaznli ovozi ko'p tomon g'olib, teng bo'lsa rad."""
    done = 0
    for app in await get_due_votings():
        yes, no = await count_votes(app["id"])
        if yes == 0 and no == 0:
            new, result, approve = "expired", "⌛ Ovoz berish muddati tugadi, hech kim ovoz bermadi.", False
            note = "Arizangiz bo'yicha hech kim ovoz bermadi va yopildi. Xohlasangiz, qayta so'rov yuborishingiz mumkin."
        elif yes > no:
            new, result, approve = "accepted", f"✅ Qabul qilindi ({yes} 👍 / {no} 👎)", True
            note = "Tabriklaymiz, arizangiz qabul qilindi! 🎉"
        else:
            new, result, approve = "rejected", f"❌ Rad etildi ({yes} 👍 / {no} 👎)", False
            note = "Afsuski, guruh a'zolari arizangizni rad etishdi."

        # ayni paytda holat o'zgargan bo'lsa, change_status False qaytaradi
        if not await change_status(app["id"], old="voting", new=new):
            continue
        done += 1
        logger.info("Ovoz berish yakunlandi: ariza %s -> %s (%s/%s)", app["id"], new, yes, no)

        try:
            if approve:
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
