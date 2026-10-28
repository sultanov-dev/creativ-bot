"""utils/url_check.py: havolani bo'laklarga ajratish (tldextract + wordninja) va soxtalik/18+ belgilari."""
from tests.table import check, same
from utils import ads
from utils.url_check import analyze


def test_domain_and_words():
    check(lambda url: (analyze(url).domain, analyze(url).words), [
        ("free-telegram-premium-gift.xyz", ("free-telegram-premium-gift.xyz", ["free", "telegram", "premium", "gift"])),
        ("http://login.example.verify-account.co.uk/x",
         ("verify-account.co.uk", ["login", "example", "verify", "account", "x"])),
        ("https://bepulsovgalar.uz/olish?id=1", ("bepulsovgalar.uz", ["bepul", "sovgalar", "olish", "id", "1"])),
        ("https://core.telegram.org/bots/api", ("telegram.org", ["core", "telegram", "bots", "api"])),
        # ichki nusxa: tarmoqsiz ham ko'p qismli suffiks to'g'ri ajraladi
        ("a.b.example.co.uk", ("example.co.uk", ["a", "b", "example"])),
    ])


def test_lookalike_and_adult_flags():
    lookalike = lambda url: analyze(url).lookalike  # noqa: E731
    adult = lambda url: analyze(url).adult  # noqa: E731
    same(lookalike, ["https://te1egram-premium.com/login", "g00gle.com", "https://1nstagram.com",
                     "http://paypa1.example.com",
                     "https://telegram.org@evil.example/a",  # "@"dan oldingisi aldash, ochiladigan sayt evil.example
                     "https://xn--80ak6aa92e.com"], True)  # аррӏе.com: kirill harflari bilan apple
    same(lookalike, ["https://core.telegram.org/bots", "https://github.com/python/cpython",
                     "https://python-telegram-bot.org/", "https://pineapple.com", "https://docs.python.org/3/",
                     "https://xn--e1afmkfd.xn--p1ai"], False)
    same(adult, ["https://www.pornhub.com/view_video.php?x=1", "xvideos2.com", "free-porn-tube.net", "hot.xxx",
                 "onlyfans.com/abc"], True)
    # yo'ldagi so'z va sussex/essex kabi nomlar 18+ emas; "sex" domenda faqat AI uchun belgi
    same(adult, ["https://en.wikipedia.org/wiki/Sex_education", "sussex.ac.uk", "https://github.com/notAI-tech/NudeNet",
                 "sexshop.uz"], False)


def test_signals_for_the_ai():
    check(lambda url, signal: signal in analyze(url).signals, [
        (("bit.ly/3abc", "url-shortener"), True), (("http://192.168.0.1/login", "ip-address"), True),
        (("free-gift.xyz", "risky-suffix .xyz"), True), (("https://a.b.c.example.com", "many-subdomains"), True),
        (("https://xn--e1afmkfd.xn--p1ai", "punycode пример.рф"), True),
        (("https://win.example/bepul-sovga", "scam-words bepul sovga"), True),
        (("https://python-telegram-bot.org/", "brand-not-official telegram"), True),
        (("sexshop.uz", "adult-words sex"), True),
    ])


async def test_analysis_goes_to_the_ai_next_to_each_link(monkeypatch):
    calls = []

    async def fake(messages, **kw):
        calls.append(messages)
        return "OK"

    monkeypatch.setattr(ads, "ask_ai", fake)
    await ads.ai_verdict("qarang", ["free-telegram-premium-gift.xyz"])
    user = calls[0][1]["content"]
    assert "words: free telegram premium gift" in user and "brand-not-official telegram" in user
