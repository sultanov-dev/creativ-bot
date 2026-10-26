from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    first_name = State()
    last_name = State()
    username = State()  # ixtiyoriy
    phone = State()  # ixtiyoriy
    age = State()
    job = State()
    about = State()
    join_group = State()
