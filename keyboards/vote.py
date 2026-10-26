from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import VoteCB


def vote_inline(app_id: int):
    builder = InlineKeyboardBuilder()

    builder.button(text="👍 Ha", callback_data=VoteCB(vote="yes", app_id=app_id))
    builder.button(text="👎 Yo'q", callback_data=VoteCB(vote="no", app_id=app_id))

    return builder.as_markup()
