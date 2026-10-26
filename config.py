import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))
# dasturchining Telegram ID(lari): bot xatolari shu yerga yuboriladi (guruh adminlariga aloqasi yo'q)
DEVELOPER_IDS = [int(x) for x in os.getenv("DEVELOPER_IDS", "").split(",") if x]
# ovoz berish shuncha daqiqa davom etadi; muddat tugagach vaznli ovozlar ko'pi g'olib bo'ladi
VOTING_MINUTES = int(os.getenv("VOTING_MINUTES") or 10)
# guruh admini ovozi oddiy a'zo ovozidan necha barobar og'ir
ADMIN_VOTE_WEIGHT = int(os.getenv("ADMIN_VOTE_WEIGHT") or 5)
if VOTING_MINUTES < 1 or ADMIN_VOTE_WEIGHT < 1:
    raise ValueError("VOTING_MINUTES va ADMIN_VOTE_WEIGHT kamida 1 bo'lishi kerak")

# AI xizmati (OpenAI formatidagi chat/completions API)
API_URL = os.getenv("API_URL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
API_MODEL = os.getenv("API_MODEL", "")

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
