import os
import re

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

# ovozlarning kamida shuncha foizi "ha" bo'lsa, a'zo guruhga qabul qilinadi (adminlar qarori kerak emas)
VOTE_ACCEPT_PERCENT = int(os.getenv("VOTE_ACCEPT_PERCENT") or 60)
if not 1 <= VOTE_ACCEPT_PERCENT <= 100:
    raise ValueError("VOTE_ACCEPT_PERCENT 1 dan 100 gacha bo'lishi kerak")

# botning guruhga yozgan xabarlari shuncha soniyadan keyin o'chadi (0 = o'chirmaslik); ovoz berish xabari bundan mustasno
AUTO_DELETE_SECONDS = int(os.getenv("AUTO_DELETE_SECONDS") or 30)

# rad etilgan/muddati o'tgan arizadan keyin yangi ariza berish uchun kutish (soniya; 0 = cheklovsiz)
REJOIN_COOLDOWN_SECONDS = int(os.getenv("REJOIN_COOLDOWN_SECONDS") or 120)
# rad etilgan, muddati o'tgan yoki chiqarilgan foydalanuvchi ma'lumotlari shuncha kun saqlanadi, keyin o'chadi (0 = o'chirmaslik)
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS") or 30)
if REJOIN_COOLDOWN_SECONDS < 0 or DATA_RETENTION_DAYS < 0:
    raise ValueError("REJOIN_COOLDOWN_SECONDS va DATA_RETENTION_DAYS manfiy bo'lmasligi kerak")

# tugallanmagan anketa shuncha soatdan keyin eskiradi: foydalanuvchi davom ettirsa, ogohlantirilib qaytadan boshlanadi (0 = eskirmaydi)
FORM_TTL_HOURS = int(os.getenv("FORM_TTL_HOURS") or 24)
if FORM_TTL_HOURS < 0:
    raise ValueError("FORM_TTL_HOURS manfiy bo'lmasligi kerak")

# AI xizmati (OpenAI formatidagi chat/completions API)
API_URL = os.getenv("API_URL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
API_MODEL = os.getenv("API_MODEL", "")
# AI xizmati rasmni (OpenAI formatidagi image_url) qabul qilsa 1: shubhali rasm/stiker AI'ga ham ko'rsatiladi
AI_VISION = os.getenv("AI_VISION", "0").strip().lower() in ("1", "true", "yes")

# foydalanuvchi bilan lichkadagi AI suhbat: shuncha xabarda hal bo'lmasa, summary bilan adminlarga uzatiladi
SUPPORT_MAX_TURNS = int(os.getenv("SUPPORT_MAX_TURNS") or 10)
# lichkadagi suhbat shuncha soat jim tursa, yopiladi (ochiq so'rov ham shuncha vaqt kutadi)
SUPPORT_TTL_HOURS = int(os.getenv("SUPPORT_TTL_HOURS") or 24)
if SUPPORT_MAX_TURNS < 1 or SUPPORT_TTL_HOURS < 1:
    raise ValueError("SUPPORT_MAX_TURNS va SUPPORT_TTL_HOURS kamida 1 bo'lishi kerak")

# Webhook rejimi: WEBHOOK_URL berilsa (ochiq https manzil, masalan https://bot.example.uz), Telegram
# yangilanishlarni shu manzilga yuboradi; berilmasa, bot long polling bilan ishlaydi.
# TLS (https) ni oldidagi reverse proxy/ingress qiladi, bot ichkarida oddiy HTTP da WEB_HOST:WEB_PORT da tinglaydi.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH") or "/webhook"
# Telegram har so'rovda shu maxfiy qiymatni yuboradi; mos kelmasa, so'rov rad etiladi (harf, raqam, _ va -)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEB_HOST = os.getenv("WEB_HOST") or "0.0.0.0"
WEB_PORT = int(os.getenv("WEB_PORT") or 8080)
if WEBHOOK_URL:
    if not WEBHOOK_URL.startswith("https://"):
        raise ValueError("WEBHOOK_URL https:// bilan boshlanishi kerak")
    if not WEBHOOK_PATH.startswith("/"):
        raise ValueError("WEBHOOK_PATH / bilan boshlanishi kerak")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", WEBHOOK_SECRET):
        raise ValueError("WEBHOOK_SECRET kerak: 16 dan 256 gacha harf, raqam, _ yoki - (masalan: openssl rand -hex 32)")

# bot.db saqlanadigan papka (Docker'da /data volume)
DATA_DIR = os.getenv("DATA_DIR", ".")
