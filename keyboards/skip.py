from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from texts import PHONE_BUTTON, SKIP_BUTTON


def skip_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=SKIP_BUTTON)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PHONE_BUTTON, request_contact=True)],
            [KeyboardButton(text=SKIP_BUTTON)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
