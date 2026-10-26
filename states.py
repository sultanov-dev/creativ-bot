from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    full_name = State()  # ism va familiya bitta savolda
    username = State()  # ixtiyoriy
    phone = State()  # ixtiyoriy
    age = State()
    job = State()
    about = State()
    join_group = State()
    review = State()  # avval to'ldirilgan anketani tasdiqlash yoki tahrirlash
