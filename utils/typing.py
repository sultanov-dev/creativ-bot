import asyncio

from aiogram import Bot
from aiogram.utils.chat_action import ChatActionSender


async def send_typing(bot: Bot, chat_id: int, text: str, delay: float = 1.0, **kwargs):
    async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
        await asyncio.sleep(delay)
        await bot.send_message(chat_id=chat_id, text=text)
