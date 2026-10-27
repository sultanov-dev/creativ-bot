from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import DecisionCB


def decision_inline(app_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Qabul qilish",
        callback_data=DecisionCB(action="accept", app_id=app_id),
    )
    builder.button(
        text="❌ Rad etish",
        callback_data=DecisionCB(action="reject", app_id=app_id),
    )

    return builder.as_markup()


def decision_confirm_inline(app_id: int, accept: bool):
    """Tasdiqlash oynasi: yakuniy qaror tugmasi va hisobotga qaytish."""
    builder = InlineKeyboardBuilder()

    if accept:
        builder.button(
            text="✅ Ha, qabul qilaman",
            callback_data=DecisionCB(action="final_accept", app_id=app_id),
        )
    else:
        builder.button(
            text="❌ Ha, rad etaman",
            callback_data=DecisionCB(action="final_reject", app_id=app_id),
        )
    builder.button(text="↩️ Orqaga", callback_data=DecisionCB(action="back", app_id=app_id))
    builder.adjust(1)

    return builder.as_markup()
