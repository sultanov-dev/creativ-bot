import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
# dasturchining Telegram ID(lari): bot xatolari shu yerga yuboriladi (guruh adminlariga aloqasi yo'q)
DEVELOPER_IDS = [int(x) for x in os.getenv("DEVELOPER_IDS", "").split(",") if x]
REQUIRED_VOTES = int(os.getenv("REQUIRED_VOTES") or 100)
if REQUIRED_VOTES < 1:
    # 0 yoki manfiy bo'lsa, birinchi ovozdayoq ariza (hatto 👎 bilan ham) qabul qilinib ketadi
    raise ValueError("REQUIRED_VOTES kamida 1 bo'lishi kerak")

# AI xizmati (OpenAI formatidagi chat/completions API)
API_URL = os.getenv("API_URL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
API_MODEL = os.getenv("API_MODEL", "")

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
