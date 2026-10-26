from html import escape

from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from callbacks import CreatorCB
from database import change_status, count_votes, get_application, get_no_votes
from keyboards.creator import creator_confirm_inline
from texts import APPLICATION_ACCEPTED, APPLICATION_REJECTED
from utils.admin import get_user_status, safe_send
from utils.summary import summarize_reasons

router = Router()


async def _edit(call: CallbackQuery, text: str, **kwargs) -> None:
    if isinstance(call.message, Message):
        try:
            await call.message.edit_text(text, **kwargs)
        except TelegramAPIError:
            pass


async def _decide(call: CallbackQuery, bot: Bot, app: dict, accepted: bool) -> None:
    """Yakuniy qaror: so'rov tasdiqlanadi yoki rad etiladi, arizachiga xabar boradi."""
    new = "accepted" if accepted else "rejected"
    if not await change_status(app["id"], old="creator_review", new=new):
        await call.answer("Bu ariza bo'yicha yakuniy qaror allaqachon qabul qilingan.", show_alert=True)
        return

    try:
        if accepted:
            await bot.approve_chat_join_request(chat_id=app["group_id"], user_id=app["user_id"])
        else:
            await bot.decline_chat_join_request(chat_id=app["group_id"], user_id=app["user_id"])
    except TelegramAPIError:
        pass  # so'rov muddati o'tgan yoki foydalanuvchi allaqachon a'zo

    result = "✅ Qabul qilindi" if accepted else "❌ Rad etildi"
    await call.answer(result)
    if isinstance(call.message, Message):
        await _edit(call, f"{call.message.html_text}\n\n{result}")

    await safe_send(
        bot=bot,
        chat_id=app["user_id"],
        text=APPLICATION_ACCEPTED if accepted else APPLICATION_REJECTED,
    )


async def _show_confirm(call: CallbackQuery, app: dict, accepted: bool, yes: int, no: int) -> None:
    """Ko'pchilikka qarshi qaror oldidan tasdiqlash oynasi.

    Qabul qilinsa (👎 ko'p yoki teng): 👎 bergan a'zolar sabablarining AI xulosasi ko'rsatiladi.
    Rad etilsa (👍 ko'p yoki teng): faqat ovoz sonlari va savol.
    """
    counts = f"Ovozlar: <b>{yes}</b> 👍 / <b>{no}</b> 👎"
    name = f"№{app['id']} <b>{escape(app['full_name'])}</b>"

    if accepted:
        # AI uzoq javob berishi mumkin: ikki marta bosilmasligi uchun avval tugmasiz holat
        await _edit(call, f"⏳ {name}: 👎 sabablari umumlashtirilmoqda…")
        head = "Ovozlar teng" if yes == no else "Ko'pchilik qarshi"
        reasons = [v["reason"] for v in await get_no_votes(app["id"])]
        summary, _ = await summarize_reasons(reasons)
        text = (
            f"⚠️ <b>{head}</b>\n\n"
            f"{name}\n{counts}\n\n"
            "👎 bergan a'zolar fikri (qisqacha xulosa):\n"
            f"{escape(summary)}\n\n"
            "Shunday bo'lsa-da, arizani qabul qilasizmi? Yakuniy qarorni tanlang."
        )
    else:
        if yes == no:
            head, note = "Ovozlar teng", "Ovozlar teng bo'lindi."
        else:
            head, note = "Ko'pchilik rozi", "A'zolarning ko'pchiligi 👍 bergan."
        text = (
            f"⚠️ <b>{head}</b>\n\n"
            f"{name}\n{counts}\n\n"
            f"{note} Arizani rad etasizmi? Yakuniy qarorni tanlang."
        )

    await _edit(call, text, reply_markup=creator_confirm_inline(app["id"]))


@router.callback_query(CreatorCB.filter())
async def on_creator_decision(call: CallbackQuery, callback_data: CreatorCB, bot: Bot):
    """Ovoz berish tugagach oxirgi qaror: faqat guruh creatori hal qiladi (ovoz natijasidan qat'i nazar).

    Ko'pchilik fikriga qarshi qaror (👎 ko'p/teng bo'lganda "Qabul", 👍 ko'p/teng bo'lganda "Rad") avval
    tasdiqlash oynasini ochadi; oynadagi "Qabul"/"Rad" tugmalari (final_*) yakuniy qaror beradi.
    """
    action = callback_data.action
    if action not in ("accept", "reject", "final_accept", "final_reject"):
        await call.answer()
        return

    app = await get_application(callback_data.app_id)
    if app is None:
        await call.answer("Kechirasiz, bu ariza topilmadi", show_alert=True)
        return

    if await get_user_status(bot, app["group_id"], call.from_user.id) != ChatMemberStatus.CREATOR:
        await call.answer("Yakuniy qarorni faqat guruh egasi qabul qiladi.", show_alert=True)
        return

    if app["status"] != "creator_review":
        await call.answer("Bu ariza bo'yicha yakuniy qaror allaqachon qabul qilingan.", show_alert=True)
        return

    accepted = action.endswith("accept")
    if action in ("accept", "reject"):
        yes, no = await count_votes(app["id"])
        # teng ovozda ikkala tugma ham tasdiqlash oynasini ochadi
        against_majority = (accepted and no >= yes) or (not accepted and yes >= no)
        if against_majority:
            await call.answer()
            await _show_confirm(call, app, accepted, yes, no)
            return

    await _decide(call, bot, app, accepted)
