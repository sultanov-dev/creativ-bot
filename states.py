from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    age = State()
    job = State()
    about = State()
    join_group = State()
