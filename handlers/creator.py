from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from callbacks import CreatorCB
from database import change_status, count_votes, get_application, get_no_votes
from keyboards.creator import creator_confirm_inline, creator_inline
from texts import APPLICATION_ACCEPTED
from utils.admin import is_admin, safe_send
from utils.summary import summarize_reasons
from utils.voting import rejection_note, report_text

router = Router()


async def _edit(call: CallbackQuery, text: str, **kwargs) -> None:
    if isinstance(call.message, Message):
        try:
            await call.message.edit_text(text, **kwargs)
        except TelegramAPIError:
            pass


async def _decide(call: CallbackQuery, bot: Bot, app: dict, accepted: bool) -> None:
    """Yakuniy qaror: so'rov tasdiqlanadi yoki rad etiladi, arizachiga xabar boradi (rad etilsa AI xulosasi bilan)."""
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
    who = escape(call.from_user.full_name)
    await _edit(call, f"{app['anketa']}\n{result} · {who}")

    # rad etilganda AI xulosasi biroz vaqt olishi mumkin: holat allaqachon yozilgan
    note = APPLICATION_ACCEPTED if accepted else await rejection_note(app["id"])
    await safe_send(bot=bot, chat_id=app["user_id"], text=note)


async def _show_confirm(call: CallbackQuery, app: dict, accepted: bool) -> None:
    """Qaror oldidan tasdiqlash oynasi.

    Qabul: 👎 bergan a'zolar sabablarining AI xulosasi. Rad: 👍 bergan a'zolar soni va "ishonchingiz komilmi?".
    """
    yes, no = await count_votes(app["id"])
    name = f"№{app['id']} <b>{escape(app['full_name'])}</b>"
    counts = f"Ovozlar: <b>{yes}</b> 👍 / <b>{no}</b> 👎"

    if accepted:
        # AI uzoq javob berishi mumkin: ikki marta bosilmasligi uchun avval tugmasiz holat
        await _edit(call, f"⏳ {name}: 👎 sabablari umumlashtirilmoqda…")
        reasons = [v["reason"] for v in await get_no_votes(app["id"])]
        summary, _ = await summarize_reasons(reasons)
        text = (
            "⚠️ <b>Qabul qilishni tasdiqlang</b>\n\n"
            f"{name}\n{counts}\n\n"
            "👎 bergan a'zolar fikri (qisqacha xulosa):\n"
            f"{escape(summary, quote=False)}\n\n"
            "Shunga qaramay, arizani qabul qilasizmi?"
        )
    else:
        text = (
            "⚠️ <b>Rad etishni tasdiqlang</b>\n\n"
            f"{name}\n{counts}\n\n"
            f"👍 bergan a'zolar: <b>{yes}</b>.\n"
            "Ishonchingiz komilmi? Arizani rad etasizmi?"
        )

    await _edit(call, text, reply_markup=creator_confirm_inline(app["id"], accepted))


@router.callback_query(CreatorCB.filter())
async def on_creator_decision(call: CallbackQuery, callback_data: CreatorCB, bot: Bot):
    """Ikkala tomon ham kerakli foizga yetmagan arizada qarorni istalgan admin qabul qiladi (birinchi bosgani amal qiladi).

    "Qabul"/"Rad" avval tasdiqlash oynasini ochadi (har doim); oynadagi "Ha" tugmasi (final_*) qaror beradi,
    "Orqaga" hisobotga qaytaradi.
    """
    action = callback_data.action
    if action not in ("accept", "reject", "final_accept", "final_reject", "back"):
        await call.answer()
        return

    app = await get_application(callback_data.app_id)
    if app is None:
        await call.answer("Kechirasiz, bu ariza topilmadi", show_alert=True)
        return

    if not is_admin(call.from_user.id):
        await call.answer("Yakuniy qarorni faqat adminlar qabul qiladi.", show_alert=True)
        return

    if app["status"] != "creator_review":
        await call.answer("Bu ariza bo'yicha yakuniy qaror allaqachon qabul qilingan.", show_alert=True)
        return

    if action == "back":
        await call.answer()
        yes, no = await count_votes(app["id"])
        await _edit(call, report_text(app, yes, no), reply_markup=creator_inline(app["id"]))
        return

    if action in ("accept", "reject"):
        await call.answer()
        await _show_confirm(call, app, accepted=action == "accept")
        return

    await _decide(call, bot, app, accepted=action == "final_accept")
