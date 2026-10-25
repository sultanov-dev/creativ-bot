import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
REQUIRED_VOTES = int(os.getenv("REQUIRED_VOTES") or 100)

# userbot (Telethon): eski a'zolarni ko'rish uchun, my.telegram.org dan olinadi
API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH", "")
USERBOT_SESSION = "userbot"
