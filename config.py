import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
REQUIRED_VOTES = int(os.getenv("REQUIRED_VOTES") or 100)

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
