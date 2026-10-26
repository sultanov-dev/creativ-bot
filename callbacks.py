from aiogram.filters.callback_data import CallbackData


class ApplicantCB(CallbackData, prefix="app"):
    action: str
    app_id: int


class VoteCB(CallbackData, prefix="vote"):
    vote: str
    app_id: int


class CreatorCB(CallbackData, prefix="creator"):
    action: str  # accept | reject | final_accept | final_reject | back
    app_id: int
