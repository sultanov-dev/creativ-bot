"""utils/url_check.py: havolani bo'laklarga ajratish (tldextract + wordninja) va soxtalik belgilari."""
import pytest

from utils import ads
from utils.url_check import analyze


class TestSplitting:
    @pytest.mark.parametrize("url,domain,words", [
        ("free-telegram-premium-gift.xyz", "free-telegram-premium-gift.xyz", ["free", "telegram", "premium", "gift"]),
        ("http://login.example.verify-account.co.uk/x", "verify-account.co.uk", ["login", "example", "verify", "account", "x"]),
        ("https://bepulsovgalar.uz/olish?id=1", "bepulsovgalar.uz", ["bepul", "sovgalar", "olish", "id", "1"]),
        ("https://core.telegram.org/bots/api", "telegram.org", ["core", "telegram", "bots", "api"]),
    ])
    def test_domain_and_words(self, url, domain, words):
        info = analyze(url)
        assert info.domain == domain and info.words == words

    def test_suffix_list_is_offline(self):
        # ichki nusxa: tarmoqsiz ham ko'p qismli suffiks to'g'ri ajraladi
        assert analyze("a.b.example.co.uk").domain == "example.co.uk"


class TestLookalike:
    @pytest.mark.parametrize("url", [
        "https://te1egram-premium.com/login", "g00gle.com", "https://1nstagram.com", "http://paypa1.example.com",
        "https://telegram.org@evil.example/a",   # "@"dan oldingisi aldash, ochiladigan sayt evil.example
        "https://xn--80ak6aa92e.com",            # аррӏе.com: kirill harflari bilan apple
    ])
    def test_forged_brand_is_definite(self, url):
        assert analyze(url).lookalike
        assert ads.classify(f"qarang {url}", None) == "danger"

    @pytest.mark.parametrize("url", [
        "https://core.telegram.org/bots", "https://github.com/python/cpython", "https://python-telegram-bot.org/",
        "https://pineapple.com", "https://docs.python.org/3/", "https://xn--e1afmkfd.xn--p1ai",
    ])
    def test_genuine_or_merely_named_domains_are_not_definite(self, url):
        assert not analyze(url).lookalike

    def test_brand_on_foreign_domain_is_only_a_hint_for_the_ai(self):
        info = analyze("https://python-telegram-bot.org/")
        assert "brand-not-official telegram" in info.signals and not info.lookalike


class TestSignals:
    @pytest.mark.parametrize("url,signal", [
        ("bit.ly/3abc", "url-shortener"), ("http://192.168.0.1/login", "ip-address"),
        ("free-gift.xyz", "risky-suffix .xyz"), ("https://a.b.c.example.com", "many-subdomains"),
        ("https://xn--e1afmkfd.xn--p1ai", "punycode пример.рф"), ("https://win.example/bepul-sovga", "scam-words bepul sovga"),
    ])
    def test_signal(self, url, signal):
        assert signal in analyze(url).signals

    async def test_analysis_goes_to_the_ai_next_to_each_link(self, monkeypatch):
        calls = []

        async def fake(messages, **kw):
            calls.append(messages)
            return "OK"

        monkeypatch.setattr(ads, "ask_ai", fake)
        await ads.ai_verdict("qarang", ["free-telegram-premium-gift.xyz"])
        user = calls[0][1]["content"]
        assert "words: free telegram premium gift" in user and "brand-not-official telegram" in user
