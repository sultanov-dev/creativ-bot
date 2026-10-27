from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from callbacks import ApplicantCB
from database import change_status, get_application
from texts import APPLICATION_REJECTED
from utils.admin import is_reviewer, mark_done, safe_send
from utils.applications import open_voting
from utils.join_requests import settle_join_request

router = Router()


@router.callback_query(ApplicantCB.filter(F.action == "reject"))
async def reject(call: CallbackQuery, callback_data: ApplicantCB, bot: Bot):
    app = await get_application(callback_data.app_id)

    if app is None:
        await call.answer("Kechirasiz, bu ariza topilmadi", show_alert=True)
        return

    user_id = app["user_id"]

    if not await is_reviewer(bot, app["group_id"], call.from_user.id):
        await call.answer("Bu amal faqat adminlar uchun.", show_alert=True)
        return

    if not await change_status(app_id=app["id"], old="pending", new="rejected"):
        await call.answer("Bu ariza allaqachon ko'rib chiqilgan.", show_alert=True)
        await mark_done(call, "⚠️ Allaqachon ko'rib chiqilgan")
        return

    await settle_join_request(bot, app, False)

    await call.answer("Ariza rad etildi")
    await mark_done(call, "❌ Rad etildi")
    await safe_send(bot=bot, chat_id=user_id, text=APPLICATION_REJECTED)


@router.callback_query(ApplicantCB.filter(F.action == "accept"))
async def accept(call: CallbackQuery, callback_data: ApplicantCB, bot: Bot):
    app = await get_application(callback_data.app_id)

    if app is None:
        await call.answer("Kechirasiz, bu ariza topilmadi", show_alert=True)
        return

    user_id = app["user_id"]

    if not await is_reviewer(bot, app["group_id"], call.from_user.id):
        await call.answer("Bu amal faqat adminlar uchun.", show_alert=True)
        return

    if not await open_voting(bot, app):
        # ikki marta bosilgan bo'lsa, ariza allaqachon pending emas
        current = await get_application(app["id"])
        if current is None or current["status"] != "pending":
            await call.answer("Bu ariza allaqachon ko'rib chiqilgan.", show_alert=True)
            await mark_done(call, "⚠️ Allaqachon ko'rib chiqilgan")
            return
        # ovoz xabari yuborilmasa, ariza qayta ko'rib chiqilishi uchun pending'da qoladi
        await call.answer(
            "Kechirasiz, ovoz berish xabarini guruhga yuborib bo'lmadi. "
            "Botning guruhda xabar yozish huquqini tekshiring.",
            show_alert=True,
        )
        return

    await call.answer(text="Ariza guruh a'zolari ovoziga qo'yildi")
    await mark_done(call, "🗳 Ovozga qo'yildi")
    await safe_send(
        bot=bot,
        chat_id=user_id,
        text=(
            "Arizangiz admin ko'rigidan o'tdi va guruh a'zolari ovoziga qo'yildi 🗳\n"
            "Natijani shu yerda xabar qilamiz, sabr qiling ⏳"
        ),
    )
