from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey


def get_private_state(storage: BaseStorage, bot: Bot, user_id: int) -> FSMContext:
    return FSMContext(
        storage=storage,
        key=StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id),
    )
