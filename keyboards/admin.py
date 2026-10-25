from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import ApplicantCB


def action_inline(group_id: int, user_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Qabul qilish",
        callback_data=ApplicantCB(
            action="accept",
            user_id=user_id,
            group_id=group_id,
        ),
    )

    builder.button(
        text="❌ Rad etish",
        callback_data=ApplicantCB(
            action="reject",
            user_id=user_id,
            group_id=group_id,
        ),
    )

    return builder.as_markup()
