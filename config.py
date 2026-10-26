import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
# dasturchining Telegram ID(lari): bot xatolari shu yerga yuboriladi (guruh adminlariga aloqasi yo'q)
DEVELOPER_IDS = [int(x) for x in os.getenv("DEVELOPER_IDS", "").split(",") if x]
# ovoz berish shuncha daqiqa davom etadi; muddat tugagach natija creatorga yuboriladi
VOTING_MINUTES = int(os.getenv("VOTING_MINUTES") or 10)
# juda katta qiymatda SQLite datetime() NULL qaytaradi va ariza abadiy "voting" da qolib ketadi
MAX_VOTING_MINUTES = 7 * 24 * 60
if not 1 <= VOTING_MINUTES <= MAX_VOTING_MINUTES:
    raise ValueError(f"VOTING_MINUTES 1 dan {MAX_VOTING_MINUTES} gacha bo'lishi kerak")

# AI xizmati (OpenAI formatidagi chat/completions API)
API_URL = os.getenv("API_URL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
API_MODEL = os.getenv("API_MODEL", "")

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
