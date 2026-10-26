import os

from dotenv import load_dotenv

load_dotenv(".env")

BOT_TOKEN = str(os.getenv("BOT_TOKEN"))

def _ids(name: str) -> list[int]:
    return [int(x) for x in os.getenv(name, "").replace(" ", "").split(",") if x]


# bot adminlarining Telegram ID(lari): anketalarni ko'rib chiqadi, yakuniy qaror qiladi va guruh buyruqlarini
# bajaradi. Guruhdagi Telegram adminlik huquqiga bog'liq emas, faqat shu ro'yxat hisoblanadi.
ADMIN_IDS = _ids("ADMIN_IDS")
# dasturchining Telegram ID(lari): bot xatolari shu yerga yuboriladi
DEVELOPER_IDS = _ids("DEVELOPER_IDS")
# ovoz berish shuncha daqiqa davom etadi; muddat tugagach natija adminlarga yuboriladi
VOTING_MINUTES = int(os.getenv("VOTING_MINUTES") or 10)
# juda katta qiymatda SQLite datetime() NULL qaytaradi va ariza abadiy "voting" da qolib ketadi
MAX_VOTING_MINUTES = 7 * 24 * 60
if not 1 <= VOTING_MINUTES <= MAX_VOTING_MINUTES:
    raise ValueError(f"VOTING_MINUTES 1 dan {MAX_VOTING_MINUTES} gacha bo'lishi kerak")

# botning guruhga yozgan xabarlari shuncha soniyadan keyin o'chadi (0 = o'chirmaslik); ovoz berish xabari bundan mustasno
AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS") or 120)

# AI xizmati (OpenAI formatidagi chat/completions API)
API_URL = os.getenv("API_URL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
API_MODEL = os.getenv("API_MODEL", "")

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
