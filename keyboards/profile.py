from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from texts import ANKETA_CONFIRM_BUTTON, PROFILE_BACK_BUTTON, PROFILE_EDIT_BUTTON, PROFILE_KEEP_BUTTON

# anketa maydoni -> tugma yozuvi (tahrirlash menyusida)
FIELD_LABELS = {
    "full_name": "👤 Ism va familiya",
    "phone": "📞 Telefon",
    "age": "🎂 Yosh",
    "job": "💼 Kasb",
    "about": "📝 O'zi haqida",
    "join_group": "❓ Qo'shilish sababi",
}
FIELD_BY_LABEL = {label: field for field, label in FIELD_LABELS.items()}


def review_keyboard() -> ReplyKeyboardMarkup:
    """Klaviatura o'rnida chiqadigan 2 qator: har qatorda bitta tugma."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PROFILE_EDIT_BUTTON)],
            [KeyboardButton(text=PROFILE_KEEP_BUTTON)],
        ],
        resize_keyboard=True,
    )


def confirm_keyboard() -> ReplyKeyboardMarkup:
    """Yangi anketa: "Tasdiqlash" va "O'zgartirish" (oddiy tugmalar, 2 qator)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=ANKETA_CONFIRM_BUTTON)],
            [KeyboardButton(text=PROFILE_EDIT_BUTTON)],
        ],
        resize_keyboard=True,
    )


def fields_keyboard() -> ReplyKeyboardMarkup:
    labels = list(FIELD_LABELS.values())
    rows = [[KeyboardButton(text=t) for t in labels[i : i + 2]] for i in range(0, len(labels), 2)]
    rows.append([KeyboardButton(text=PROFILE_BACK_BUTTON)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
