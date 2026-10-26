from aiogram.utils.keyboard import InlineKeyboardBuilder

from callbacks import ProfileCB

# anketa maydoni -> tugma yozuvi (tahrirlash menyusida)
FIELD_LABELS = {
    "full_name": "👤 Ism va familiya",
    "username": "🔗 Username",
    "phone": "📞 Telefon",
    "age": "🎂 Yosh",
    "job": "💼 Kasb",
    "about": "📝 O'zi haqida",
    "join_group": "❓ Qo'shilish sababi",
}


def review_inline():
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ O'zgartirish", callback_data=ProfileCB(action="edit"))
    builder.button(text="✅ Shunday qoldirish", callback_data=ProfileCB(action="keep"))
    builder.adjust(1)
    return builder.as_markup()


def fields_inline():
    builder = InlineKeyboardBuilder()
    for field, label in FIELD_LABELS.items():
        builder.button(text=label, callback_data=ProfileCB(action="field", field=field))
    builder.button(text="⬅️ Orqaga", callback_data=ProfileCB(action="back"))
    builder.adjust(1)
    return builder.as_markup()
