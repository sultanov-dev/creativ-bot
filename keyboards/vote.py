from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import VoteCB


def vote_inline(app_id: int, yes: int = 0, no: int = 0):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"👍 Ha ({yes})", callback_data=VoteCB(vote="yes", app_id=app_id)
    )
    builder.button(
        text=f"👎 Yo'q ({no})", callback_data=VoteCB(vote="no", app_id=app_id)
    )

    return builder.as_markup()
