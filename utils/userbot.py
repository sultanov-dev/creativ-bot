import logging

from telethon import TelegramClient

from config import API_HASH, API_ID, USERBOT_SESSION

logger = logging.getLogger(__name__)

client: TelegramClient | None = (
    TelegramClient(USERBOT_SESSION, API_ID, API_HASH) if API_ID and API_HASH else None
)


async def start() -> bool:
    """Saqlangan sessiya bilan ulanadi. Sessiya yo'q bo'lsa `userbot_login.py` ishga tushiriladi."""
    if client is None:
        logger.info("API_ID/API_HASH berilmagan, userbot o'chiq")
        return False

    await client.connect()
    if not await client.is_user_authorized():
        logger.warning("Userbot sessiyasi yo'q: avval `python userbot_login.py` ni ishga tushiring")
        await client.disconnect()
        return False

    # chat ID larni Telethon keshiga yuklash
    await client.get_dialogs()
    return True


async def stop() -> None:
    if client is not None and client.is_connected():
        await client.disconnect()


def is_ready() -> bool:
    return client is not None and client.is_connected()


async def list_deleted(group_id: int) -> list[int]:
    """Guruhdagi o'chirilgan akkauntlar ID ro'yxati."""
    if client is None:
        return []

    return [
        user.id
        async for user in client.iter_participants(group_id)
        if getattr(user, "deleted", False)
    ]
