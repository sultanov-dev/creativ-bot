"""Guruhdagi Telegram havolalarini (t.me ...) AI'dan oldin bot o'zi tekshiradi: AI har safar chaqirilmasin.

1. Shu guruhning o'z xabari yoki havolasi (t.me/c/<guruh>/..., t.me/<guruh_username>/...) — shubha emas.
2. Aniq reklama — AI'siz o'chiriladi: yopiq guruh/kanalga taklif (t.me/+..., joinchat, addlist), referal parametr
   (?start=, ?startapp=, ref), aniq reklama so'zlari ("obuna bo'ling", "kanalimiz", "bonus"...), izohsiz yalang'och
   havola, yoki shu manzil yaqinda AI tomonidan reklama deb topilgan (xotiradagi qora ro'yxat).
3. Qolganini AI hal qiladi (masalan, foydali dasturlash kanalining posti bilan bo'lishish).
"""
import re
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

TG_HOSTS = frozenset(("t.me", "telegram.me", "telegram.dog", "telesco.pe"))
# reklama ekanini AI'siz bildiradigan so'zlar (utils.ads.PROMO_RE dan torroq: "kanal", "kurs" kabi oddiy so'zlarsiz)
STRONG_PROMO_RE = re.compile(
    r"obuna\s*bo|obuna\s*qil|подпиш|подписывай|kanalimiz|guruhimiz|наш(?:ем|ему)?\s*канал|qo'?shil(?:ing|inglar)|"
    r"присоединя|вступай|reklam|реклам|zarabot|заработ|pul\s*ishla|daromad|доход|referal|реферал|promokod|промокод|"
    r"bonus|бонус|kazino|казино|casino|1xbet|mostbet|melbet|stavk|ставк|aksiya|акци[яи]|chegirma|скидк|kripto|"
    r"crypto|signal|sovg'?a|подарок|bepul|бесплатн",
    re.IGNORECASE,
)
_REF_PARAMS = ("start", "startapp", "startgroup", "ref", "referral", "invite")
_WORD_RE = re.compile(r"[^\W\d_]{2,}")

# AI reklama/xavfli deb topgan Telegram manzillari: shu manzil yana kelsa, AI chaqirilmaydi
BLOCK_TTL = 24 * 3600
_BLOCK_MAX = 2000
_blocked: dict[str, float] = {}


@dataclass(frozen=True)
class TgLink:
    url: str
    key: str  # bir xil manzil uchun bir xil kalit (qora ro'yxat uchun)
    username: str = ""  # t.me/<username>/...
    internal_id: str = ""  # t.me/c/<id>/<xabar>
    invite: bool = False  # t.me/+hash, joinchat, addlist
    referral: bool = False  # ?start=..., ?startapp=..., ref


def parse(url: str) -> TgLink | None:
    """Telegram havolasi bo'lsa uning tahlili, aks holda None."""
    raw = url.strip().rstrip(".,;:!?)»\"'")
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host not in TG_HOSTS:
        return None
    segments = [s for s in parts.path.split("/") if s]
    query = {k.lower() for k in parse_qs(parts.query, keep_blank_values=True)}
    referral = any(p in query for p in _REF_PARAMS)
    if not segments:
        return TgLink(raw, key=host, referral=referral)
    first = segments[0]
    if first.startswith("+") or first.lower() in ("joinchat", "addlist"):
        code = first[1:] if first.startswith("+") else (segments[1] if len(segments) > 1 else "")
        return TgLink(raw, key=f"invite:{code}", invite=True, referral=referral)
    if first.lower() == "c" and len(segments) > 1:
        return TgLink(raw, key=f"c:{segments[1]}", internal_id=segments[1], referral=referral)
    if first.lower() in ("s", "share") and len(segments) > 1:  # t.me/s/<kanal> — kanalning veb ko'rinishi
        first = segments[1]
    name = first.lower()
    return TgLink(raw, key=f"u:{name}", username=name, referral=referral)


def is_own(link: TgLink, chat_id: int | None, chat_username: str | None) -> bool:
    """Shu guruhning o'z xabari yoki havolasi."""
    if link.internal_id and chat_id is not None and str(chat_id) == f"-100{link.internal_id}":
        return True
    return bool(link.username and chat_username and link.username == chat_username.lower())


def is_blocked(link: TgLink) -> bool:
    until = _blocked.get(link.key)
    return until is not None and until > time.monotonic()


def remember_ad(links: list[TgLink]) -> None:
    """AI reklama/xavfli degan xabardagi Telegram manzillari BLOCK_TTL davomida AI'siz o'chiriladi."""
    now = time.monotonic()
    if len(_blocked) >= _BLOCK_MAX:
        for key in [k for k, t in _blocked.items() if t <= now]:
            del _blocked[key]
        while len(_blocked) >= _BLOCK_MAX:  # hammasi hali amalda: eng eskisi chiqariladi
            del _blocked[next(iter(_blocked))]
    for link in links:
        _blocked[link.key] = now + BLOCK_TTL


def obvious_ad(text: str, tg_urls: list[str], links: list[TgLink]) -> bool:
    """AI'siz aniq reklama: taklif yoki referal havola, reklama so'zlari, izohsiz havola yoki qora ro'yxatdagi manzil."""
    if any(link.invite or link.referral or is_blocked(link) for link in links):
        return True
    if STRONG_PROMO_RE.search(text):
        return True
    rest = text
    for url in tg_urls:
        rest = rest.replace(url, " ")
    return len(_WORD_RE.findall(rest)) < 2  # havoladan boshqa deyarli hech narsa yozilmagan
