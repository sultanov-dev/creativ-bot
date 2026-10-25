import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
REQUIRED_VOTES = int(os.getenv("REQUIRED_VOTES") or 100)
