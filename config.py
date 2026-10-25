import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
# dasturchining Telegram ID(lari): bot xatolari shu yerga yuboriladi (guruh adminlariga aloqasi yo'q)
DEVELOPER_IDS = [int(x) for x in os.getenv("DEVELOPER_IDS", "").split(",") if x]
REQUIRED_VOTES = int(os.getenv("REQUIRED_VOTES") or 100)

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
