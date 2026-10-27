from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from callbacks import DecisionCB
from database import change_status, count_votes, get_application, get_no_votes
from keyboards.decision import decision_confirm_inline, decision_inline
from texts import APPLICATION_ACCEPTED, APPLICATION_ACCEPTED_NOT_JOINED
from utils.admin import is_admin, join_failed_text, notify_admins, safe_send, status_text
from utils.join_requests import settle_join_request
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
    if not await change_status(app["id"], old="admin_decision", new=new):
        await call.answer("Bu ariza bo'yicha yakuniy qaror allaqachon qabul qilingan.", show_alert=True)
        return

    joined = await settle_join_request(bot, app, accepted)

    result = "✅ Qabul qilindi" if accepted else "❌ Rad etildi"
    if accepted and not joined:
        result = "⚠️ Qabul qilindi, lekin guruhga qo'shib bo'lmadi"
    await call.answer(result)
    who = escape(call.from_user.full_name)
    await _edit(call, f"{app['anketa']}\n{result} · {who}")

    # boshqa adminlarga ham natija statusi (qaror qilgan adminda xabar tahrirlandi)
    await notify_admins(
        bot,
        (status_text(app, accepted, f" (qaror: {who})") if joined else join_failed_text(app)),
        exclude=(call.from_user.id,),
    )

    # rad etilganda AI xulosasi biroz vaqt olishi mumkin: holat allaqachon yozilgan
    if accepted:
        note = APPLICATION_ACCEPTED if joined else APPLICATION_ACCEPTED_NOT_JOINED
    else:
        note = await rejection_note(app["id"])
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

    await _edit(call, text, reply_markup=decision_confirm_inline(app["id"], accepted))


@router.callback_query(DecisionCB.filter())
async def on_decision(call: CallbackQuery, callback_data: DecisionCB, bot: Bot):
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

    if app["status"] != "admin_decision":
        await call.answer("Bu ariza bo'yicha yakuniy qaror allaqachon qabul qilingan.", show_alert=True)
        return

    if action == "back":
        await call.answer()
        await _edit(call, report_text(app), reply_markup=decision_inline(app["id"]))
        return

    if action in ("accept", "reject"):
        await call.answer()
        await _show_confirm(call, app, accepted=action == "accept")
        return

    await _decide(call, bot, app, accepted=action == "final_accept")
