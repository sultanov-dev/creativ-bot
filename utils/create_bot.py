from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN


def create_bot(token: str, parse_mode: ParseMode = ParseMode.HTML) -> Bot:
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=parse_mode),
    )


bot = create_bot(token=BOT_TOKEN)
