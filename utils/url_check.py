"""Havolani bo'laklarga ajratib tahlil qilish (AI'dan oldin, mahalliy).

tldextract (github.com/john-kurkowski/tldextract): Public Suffix List bo'yicha domenni subdomen / asosiy domen / suffiksga
ajratadi (login.paypa1.verify-account.co.uk -> asosiy domen verify-account.co.uk). Ro'yxat paket ichidagi nusxadan
olinadi: tarmoqqa chiqmaydi. wordninja (github.com/keredson/wordninja): bo'shliqsiz matnni so'zlarga ajratadi
(freetelegrampremiumgift -> free telegram premium gift); lug'atiga o'zbekcha/ruscha (lotincha) firibgarlik so'zlari va
brendlar qo'shilgan.

Natija ikki joyda ishlatiladi: aniq soxtalik belgisi (te1egram, paypa1 kabi raqam bilan yasalgan brend nomi yoki
"telegram.org@boshqa-sayt" hiylasi) AI'siz xavfli hisoblanadi; qolgan belgilar AI'ga havola yonida beriladi.
"""
import gzip
import ipaddress
import os
import re
from dataclasses import dataclass, field
from math import log
from urllib.parse import unquote, urlsplit

import tldextract
import wordninja

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # faqat ichki nusxa, tarmoq yo'q

# brend -> uning rasmiy asosiy domenlari
BRANDS: dict[str, tuple[str, ...]] = {
    "telegram": ("telegram.org", "t.me", "telegram.me", "telegram.dog", "telesco.pe"),
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com", "fb.com"),
    "whatsapp": ("whatsapp.com", "whatsapp.net", "wa.me"),
    "google": ("google.com", "google.ru", "google.co.uz", "googleapis.com", "goo.gl"),
    "youtube": ("youtube.com", "youtu.be"),
    "apple": ("apple.com", "icloud.com"),
    "microsoft": ("microsoft.com", "live.com", "office.com"),
    "github": ("github.com", "github.io", "githubusercontent.com"),
    "paypal": ("paypal.com",),
    "binance": ("binance.com",),
    "steam": ("steampowered.com", "steamcommunity.com"),
    "tiktok": ("tiktok.com",),
    "payme": ("payme.uz",),
    "uzcard": ("uzcard.uz",),
    "kapitalbank": ("kapitalbank.uz",),
}
SHORTENERS = frozenset((
    "bit.ly", "tinyurl.com", "cutt.ly", "clck.ru", "goo.su", "is.gd", "rb.gy", "shorturl.at", "tiny.cc", "t.co",
    "ow.ly", "buff.ly", "rebrand.ly", "v.gd", "u.to", "qps.ru", "vk.cc", "surl.li", "linktr.ee",
))
RISKY_SUFFIXES = frozenset((
    "xyz", "top", "click", "icu", "buzz", "cyou", "monster", "rest", "tk", "ml", "ga", "cf", "gq", "win", "bet",
    "casino", "xxx", "porn", "sex", "adult", "loan", "bid", "pw",
))
# 18+ sayt: domen nomida shu so'z bo'lsa yoki domen oxiri shunday bo'lsa — AI'siz xavfli (yo'l qismi hisobga
# olinmaydi: wikipedia.org/wiki/Sex_education kabi sahifalar oddiy). "sex" bu yerda yo'q: sussex, essex kabi
# nomlarda ham uchraydi, u faqat AI uchun belgi (adult-words)
ADULT_WORDS = frozenset((
    "porn", "porno", "porntube", "xxx", "hentai", "nsfw", "pornhub", "xvideos", "xnxx", "xhamster", "onlyfans",
    "brazzers", "redtube", "youporn", "chaturbate", "stripchat", "bongacams", "spankbang", "eporner", "rule34",
    "erotic", "erotica", "nudes", "camgirl", "camgirls",
))
ADULT_HINT_WORDS = frozenset(("sex", "sexy", "seks", "nude", "intim", "escort", "milf", "dating"))
ADULT_SUFFIXES = frozenset(("xxx", "porn", "sex", "adult"))
SCAM_WORDS = frozenset((
    "free", "gift", "gifts", "prize", "bonus", "premium", "giveaway", "airdrop", "claim", "verify", "verification",
    "login", "signin", "wallet", "casino", "bet", "betting", "jackpot", "porn", "xxx", "sex", "nft", "stars",
    "crack", "keygen", "mod", "hack", "bepul", "sovga", "sovgalar", "yutuq", "yutib", "pul", "kazino", "stavka",
    "besplatno", "podarok", "vyigrysh", "zarabotok", "aksiya",
))
# lug'atga qo'shiladigan so'zlar (eng yuqori ustuvorlik): o'zbekcha/ruscha lotincha so'zlar va brendlar
_EXTRA_WORDS = sorted(SCAM_WORDS | ADULT_WORDS | ADULT_HINT_WORDS | set(BRANDS) | {
    "ishlash", "ishla", "daromad", "kanal", "guruh", "obuna", "chegirma", "kredit", "tekin", "yutuqli", "olish",
    "uz", "uzb", "toshkent", "dostavka", "skidka", "kripto", "signal", "signallar",
})
_LEET = (str.maketrans("013457", "oleast"), str.maketrans("013457", "oieast"))
# punycode domenlarda lotin harfiga o'xshash kirill/boshqa harflar (аррӏе.com -> apple.com)
_CONFUSABLES = str.maketrans("аеорсухӏіјԁѕԛԝɡһкмтвпг", "aeopcyxlijdsqwghkmtbnr")


class _Model(wordninja.LanguageModel):
    """wordninja modeli: o'z so'zlarimiz standart inglizcha lug'atdan oldin (ya'ni ko'proq ehtimolli) turadi."""

    def __init__(self) -> None:  # ota-klass faylni o'qiydi, bu yerda ro'yxatni o'zimiz yig'amiz
        path = os.path.join(os.path.dirname(os.path.abspath(wordninja.__file__)), "wordninja", "wordninja_words.txt.gz")
        with gzip.open(path) as f:
            base = f.read().decode().split()
        words = list(dict.fromkeys([*_EXTRA_WORDS, *base]))
        self._wordcost = {k: log((i + 1) * log(len(words))) for i, k in enumerate(words)}
        self._maxword = max(len(x) for x in words)


_MODEL = _Model()
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class UrlInfo:
    url: str
    host: str = ""
    domain: str = ""  # asosiy (ro'yxatdan o'tgan) domen, masalan verify-account.co.uk
    words: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    lookalike: bool = False  # aniq soxtalik: AI'siz xavfli
    adult: bool = False  # 18+ sayt: AI'siz xavfli

    def describe(self) -> str:
        """AI uchun bir qator: asosiy domen, so'zlar va belgilar."""
        parts = [f"domain: {self.domain or self.host or '?'}"]
        if self.words:
            parts.append("words: " + " ".join(self.words[:25]))
        if self.signals:
            parts.append("signals: " + ", ".join(self.signals))
        return "; ".join(parts)


def _split(text: str) -> list[str]:
    words: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        words.extend(w for w in _MODEL.split(token) if w)
    return words


def _brands_in(text: str) -> set[str]:
    words = set(_split(text))
    return {b for b in BRANDS if b in words or (len(b) >= 6 and b in text)}


def analyze(url: str) -> UrlInfo:
    raw = url.strip().rstrip(".,;:!?)»\"'")
    info = UrlInfo(url=raw)
    parts = urlsplit(raw if re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE) else f"http://{raw}")
    netloc = parts.netloc.lower()
    if "@" in netloc:
        # https://telegram.org@evil.example: brauzer "evil.example"ni ochadi, "@"dan oldingisi aldash uchun
        info.signals.append("userinfo-trick")
        info.lookalike = True
        netloc = netloc.rsplit("@", 1)[1]
    host = netloc.rsplit(":", 1)[0] if not netloc.startswith("[") else netloc
    info.host = host
    name = ""  # domen nomi suffikssiz (so'zlarga ajratiladi)

    try:
        ipaddress.ip_address(host.strip("[]"))
        info.signals.append("ip-address")
        info.domain = host
    except ValueError:
        ext = _EXTRACT(host)
        info.domain = ".".join(p for p in (ext.domain, ext.suffix) if p)
        if ext.suffix in RISKY_SUFFIXES:
            info.signals.append(f"risky-suffix .{ext.suffix}")
        if ext.subdomain.count(".") >= 2:
            info.signals.append("many-subdomains")
        if info.domain in SHORTENERS:
            info.signals.append("url-shortener")
        labels = [label for label in host.split(".") if label]
        if any(label.startswith("xn--") for label in labels):
            try:
                unicode_host = host.encode().decode("idna")
            except UnicodeError:
                unicode_host = ""
            info.signals.append(f"punycode {unicode_host}".strip())
            latin = unicode_host.translate(_CONFUSABLES)
            # haqiqiy domen xn--... (rasmiy emas): lotinga o'xshatilganda brend chiqsa, bu ataylab yasalgan nusxa
            for brand in sorted(b for b in BRANDS if len(b) >= 5 and b in latin):
                info.signals.append(f"lookalike {brand}")
                info.lookalike = True

        name = ".".join(p for p in (ext.subdomain, ext.domain) if p)
        official = any(info.domain in domains for domains in BRANDS.values())
        if not official:
            plain = _brands_in(name)
            for brand in sorted(plain):
                info.signals.append(f"brand-not-official {brand}")
            # raqam bilan yasalgan brend nomi (te1egram, paypa1, g00gle): tasodifan bo'lmaydi
            leet = set().union(*(_brands_in(name.translate(table)) for table in _LEET)) - plain
            for brand in sorted(b for b in leet if len(b) >= 5):
                info.signals.append(f"lookalike {brand}")
                info.lookalike = True

    host_words = set(_split(name))
    suffix = info.domain.rsplit(".", 1)[-1] if "." in info.domain else ""
    adult = sorted(host_words & ADULT_WORDS) + ([f".{suffix}"] if suffix in ADULT_SUFFIXES else [])
    if adult:
        info.signals.append("adult " + " ".join(adult))
        info.adult = True
    elif host_words & ADULT_HINT_WORDS:
        info.signals.append("adult-words " + " ".join(sorted(host_words & ADULT_HINT_WORDS)))

    path = unquote(f"{parts.path} {parts.query}")
    info.words = _split(name) + _split(path)
    hits = sorted({w for w in info.words if w in SCAM_WORDS})
    if hits:
        info.signals.append("scam-words " + " ".join(hits))
    return info
