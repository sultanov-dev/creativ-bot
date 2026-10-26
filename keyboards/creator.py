from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import CreatorCB


def creator_inline(app_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text="✅ Qabul qilaman",
        callback_data=CreatorCB(action="accept", app_id=app_id),
    )
    builder.button(
        text="❌ Rad qilaman",
        callback_data=CreatorCB(action="reject", app_id=app_id),
    )

    return builder.as_markup()
