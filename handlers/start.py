from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Salom, {message.from_user.full_name if message.from_user is not None else None}! Men Choyxona botiman ☕"
    )
