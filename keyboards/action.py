from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import ApplicantCB


def action_inline(app_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Qabul qilish",
        callback_data=ApplicantCB(action="accept", app_id=app_id),
    )

    builder.button(
        text="❌ Rad etish",
        callback_data=ApplicantCB(action="reject", app_id=app_id),
    )

    return builder.as_markup()
