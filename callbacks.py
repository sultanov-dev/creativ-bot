from aiogram.filters.callback_data import CallbackData


class ApplicantCB(CallbackData, prefix="app"):
    action: str
    app_id: int


class VoteCB(CallbackData, prefix="vote"):
    vote: str
    app_id: int


class CreatorCB(CallbackData, prefix="creator"):
    action: str
    app_id: int


class ProfileCB(CallbackData, prefix="prof"):
    action: str  # keep | edit | back | field
    field: str = ""
