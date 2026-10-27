"""config.py: muhit o'zgaruvchilarini tekshirish (noto'g'ri qiymat bilan bot ishga tushmasligi kerak)."""
import importlib

import pytest

import config


@pytest.fixture
def reload_config(monkeypatch):
    def _reload(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


class TestIds:
    def test_comma_separated_with_spaces(self, reload_config):
        assert reload_config(ADMIN_IDS=" 1, 2 ,3 ").ADMIN_IDS == [1, 2, 3]

    def test_empty_means_nobody(self, reload_config):
        assert reload_config(ADMIN_IDS="").ADMIN_IDS == []

    def test_trailing_comma(self, reload_config):
        assert reload_config(ADMIN_IDS="1,,2,").ADMIN_IDS == [1, 2]

    def test_non_numeric_id_fails_fast(self, reload_config):
        with pytest.raises(ValueError):
            reload_config(ADMIN_IDS="1,abc")

    def test_negative_ids_are_accepted_as_is(self, reload_config):
        assert reload_config(ADMIN_IDS="-5").ADMIN_IDS == [-5]


class TestVotingMinutes:
    @pytest.mark.parametrize("value,expected", [("1", 1), ("10", 10), ("10080", 10080)])
    def test_bounds_ok(self, reload_config, value, expected):
        assert reload_config(VOTING_MINUTES=value).VOTING_MINUTES == expected

    @pytest.mark.parametrize("value", ["0", "-1", "10081", "99999999999"])
    def test_out_of_range(self, reload_config, value):
        with pytest.raises(ValueError):
            reload_config(VOTING_MINUTES=value)

    def test_empty_uses_default(self, reload_config):
        assert reload_config(VOTING_MINUTES="").VOTING_MINUTES == 10

    def test_not_a_number(self, reload_config):
        with pytest.raises(ValueError):
            reload_config(VOTING_MINUTES="abc")


class TestAcceptPercent:
    @pytest.mark.parametrize("value", ["1", "60", "100"])
    def test_ok(self, reload_config, value):
        assert reload_config(VOTE_ACCEPT_PERCENT=value).VOTE_ACCEPT_PERCENT == int(value)

    @pytest.mark.parametrize("value", ["0", "101", "-5"])
    def test_out_of_range(self, reload_config, value):
        with pytest.raises(ValueError):
            reload_config(VOTE_ACCEPT_PERCENT=value)

    def test_empty_uses_default(self, reload_config):
        assert reload_config(VOTE_ACCEPT_PERCENT="").VOTE_ACCEPT_PERCENT == 60


class TestAutoDelete:
    def test_zero_disables(self, reload_config):
        assert reload_config(AUTO_DELETE_SECONDS="0").AUTO_DELETE_SECONDS == 0

    def test_default(self, reload_config):
        assert reload_config(AUTO_DELETE_SECONDS="").AUTO_DELETE_SECONDS == 30


class TestWebhook:
    SECRET = "a" * 32

    def test_disabled_by_default(self, reload_config):
        cfg = reload_config(WEBHOOK_URL="")
        assert cfg.WEBHOOK_URL == "" and cfg.WEBHOOK_PATH == "/webhook" and cfg.WEB_PORT == 8080

    def test_valid(self, reload_config):
        cfg = reload_config(WEBHOOK_URL="https://bot.example.uz/", WEBHOOK_SECRET=self.SECRET, WEBHOOK_PATH="/hook")
        assert cfg.WEBHOOK_URL == "https://bot.example.uz"  # oxirgi "/" olib tashlanadi
        assert cfg.WEBHOOK_PATH == "/hook"

    def test_http_url_rejected(self, reload_config):
        with pytest.raises(ValueError):
            reload_config(WEBHOOK_URL="http://bot.example.uz", WEBHOOK_SECRET=self.SECRET)

    def test_path_must_start_with_slash(self, reload_config):
        with pytest.raises(ValueError):
            reload_config(WEBHOOK_URL="https://x.uz", WEBHOOK_SECRET=self.SECRET, WEBHOOK_PATH="hook")

    @pytest.mark.parametrize("secret", ["", "short", "a" * 15, "a" * 257, "bad secret bad secret!", "a" * 15 + "%"])
    def test_weak_or_invalid_secret_rejected(self, reload_config, secret):
        with pytest.raises(ValueError):
            reload_config(WEBHOOK_URL="https://x.uz", WEBHOOK_SECRET=secret)

    @pytest.mark.parametrize("secret", ["a" * 16, "a" * 256, "AbC_-" * 4])
    def test_boundary_secrets_accepted(self, reload_config, secret):
        reload_config(WEBHOOK_URL="https://x.uz", WEBHOOK_SECRET=secret)

    def test_whitespace_in_url_is_stripped(self, reload_config):
        assert reload_config(WEBHOOK_URL="  https://x.uz  ", WEBHOOK_SECRET=self.SECRET).WEBHOOK_URL == "https://x.uz"


def test_env_file_cannot_override_test_environment():
    # conftest barcha kalitlarni o'rnatadi: haqiqiy .env qiymatlari testlarga o'tmaydi
    assert config.BOT_TOKEN == "123456:TESTTOKEN"
    assert config.ADMIN_IDS == [1001, 1002]
    assert config.WEBHOOK_URL == ""
