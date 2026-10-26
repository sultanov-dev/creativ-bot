from aiogram import Bot

from utils.admin import get_group_creator_id, safe_send


async def send_to_creator(bot: Bot, group_id: int, text: str) -> None:
    creator_id = await get_group_creator_id(bot, group_id)
    if creator_id is not None:
        await safe_send(bot=bot, chat_id=creator_id, text=text)
