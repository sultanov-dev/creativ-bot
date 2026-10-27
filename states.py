from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    full_name = State()  # ism va familiya bitta savolda
    phone = State()  # ixtiyoriy
    age = State()
    job = State()
    about = State()
    join_group = State()
    review = State()  # avval to'ldirilgan anketani tasdiqlash yoki tahrirlash
    pick_field = State()  # tahrirlash: qaysi maydonni o'zgartirish
