from aiogram.filters.callback_data import CallbackData


class ApplicantCB(CallbackData, prefix="app"):
    action: str
    user_id: int
    group_id: int
