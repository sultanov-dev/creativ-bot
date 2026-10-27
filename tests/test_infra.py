"""Infratuzilma: config.py (muhit o'zgaruvchilari), utils/fsm_storage.py (FSM holati) va main.py (webhook)."""
import importlib
from collections.abc import AsyncIterator, Callable, Iterator
from types import ModuleType

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiohttp.test_utils import TestClient, TestServer

import config
import database
import main
from states import Form
from tests.telegram_fakes import make_bot
from utils.fsm import get_private_state
from utils.fsm_storage import SQLiteStorage

# ------------------------------------------------------------------ config.py


@pytest.fixture
def reload_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., ModuleType]]:
    def _reload(**env: str) -> ModuleType:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


SECRET = "a" * 32
WEBHOOK = {"WEBHOOK_URL": "https://x.uz", "WEBHOOK_SECRET": SECRET}


@pytest.mark.parametrize("raw,expected", [(" 1, 2 ,3 ", [1, 2, 3]), ("", []), ("1,,2,", [1, 2]), ("-5", [-5])])
def test_admin_ids_parsing(reload_config, raw, expected):
    assert reload_config(ADMIN_IDS=raw).ADMIN_IDS == expected


@pytest.mark.parametrize("name,value,expected", [
    ("VOTING_MINUTES", "1", 1), ("VOTING_MINUTES", "10080", 10080), ("VOTING_MINUTES", "", 10),
    ("VOTE_ACCEPT_PERCENT", "1", 1), ("VOTE_ACCEPT_PERCENT", "100", 100), ("VOTE_ACCEPT_PERCENT", "", 60),
    ("AUTO_DELETE_SECONDS", "0", 0), ("AUTO_DELETE_SECONDS", "", 30),
])
def test_numeric_settings_ok_and_defaults(reload_config, name, value, expected):
    assert getattr(reload_config(**{name: value}), name) == expected


@pytest.mark.parametrize("name,value", [
    ("ADMIN_IDS", "1,abc"),
    ("VOTING_MINUTES", "0"), ("VOTING_MINUTES", "-1"), ("VOTING_MINUTES", "10081"), ("VOTING_MINUTES", "abc"),
    ("VOTE_ACCEPT_PERCENT", "0"), ("VOTE_ACCEPT_PERCENT", "101"), ("VOTE_ACCEPT_PERCENT", "-5"),
])
def test_invalid_values_fail_fast(reload_config, name, value):
    with pytest.raises(ValueError):
        reload_config(**{name: value})


class TestWebhookConfig:
    def test_disabled_by_default(self, reload_config):
        cfg = reload_config(WEBHOOK_URL="")
        assert cfg.WEBHOOK_URL == "" and cfg.WEBHOOK_PATH == "/webhook" and cfg.WEB_PORT == 8080

    def test_valid_url_is_normalized(self, reload_config):
        cfg = reload_config(WEBHOOK_URL="  https://bot.example.uz/  ", WEBHOOK_SECRET=SECRET, WEBHOOK_PATH="/hook")
        assert cfg.WEBHOOK_URL == "https://bot.example.uz" and cfg.WEBHOOK_PATH == "/hook"

    @pytest.mark.parametrize("extra", [
        {"WEBHOOK_URL": "http://bot.example.uz"},  # faqat https
        {"WEBHOOK_PATH": "hook"},  # "/" bilan boshlanishi shart
        *({"WEBHOOK_SECRET": s} for s in ["", "short", "a" * 15, "a" * 257, "bad secret bad secret!", "a" * 15 + "%"]),
    ])
    def test_invalid_webhook_settings_rejected(self, reload_config, extra):
        with pytest.raises(ValueError):
            reload_config(**WEBHOOK | extra)

    @pytest.mark.parametrize("secret", ["a" * 16, "a" * 256, "AbC_-" * 4])
    def test_boundary_secrets_accepted(self, reload_config, secret):
        reload_config(**WEBHOOK | {"WEBHOOK_SECRET": secret})


def test_env_file_cannot_override_test_environment():
    # conftest barcha kalitlarni o'rnatadi: haqiqiy .env qiymatlari testlarga o'tmaydi
    assert config.BOT_TOKEN == "123456:TESTTOKEN"
    assert config.ADMIN_IDS == [1001, 1002]
    assert config.WEBHOOK_URL == ""


# ------------------------------------------------------------------ fsm_storage.py


def key(user: int = 1, chat: int | None = None, bot_id: int = 123456) -> StorageKey:
    return StorageKey(bot_id=bot_id, chat_id=user if chat is None else chat, user_id=user)


async def test_state_and_data_roundtrip(db):
    s = SQLiteStorage()
    assert await s.get_state(key()) is None and await s.get_data(key()) == {}
    await s.set_state(key(), Form.age)
    assert await s.get_state(key()) == Form.age.state
    await s.set_state(key(), "custom:state")
    assert await s.get_state(key()) == "custom:state"
    await s.set_data(key(), {"a": 1, "b": "ўзбек"})
    assert await s.get_data(key()) == {"a": 1, "b": "ўзбек"}
    await s.set_data(key(), {})
    assert await s.get_data(key()) == {}
    await s.close()  # hech narsa qilmaydi


async def test_clearing_state_deletes_row_but_keeps_data_independent(db):
    s = SQLiteStorage()
    await s.set_state(key(), Form.job)
    await s.set_data(key(), {"x": 1})
    await s.set_state(key(), None)
    assert await s.get_state(key()) is None and await s.get_data(key()) == {"x": 1}
    await s.set_data(key(), {})
    d = await database.get_db()
    row = await (await d.execute("SELECT COUNT(*) FROM fsm")).fetchone()
    assert row is not None and row[0] == 0


async def test_keys_are_isolated_per_user_and_chat(db):
    s = SQLiteStorage()
    for k, value in [(key(1), 1), (key(2), 2), (key(1, chat=-5), "group")]:
        await s.set_data(k, {"u": value})
    assert [(await s.get_data(k))["u"] for k in (key(1), key(2), key(1, chat=-5))] == [1, 2, "group"]


async def test_survives_connection_restart(db):
    s = SQLiteStorage()
    await s.set_state(key(), Form.about)
    await s.set_data(key(), {"full_name": "A B"})
    await database.close_db()
    assert await SQLiteStorage().get_state(key()) == Form.about.state
    assert await SQLiteStorage().get_data(key()) == {"full_name": "A B"}


async def test_get_private_state_uses_user_as_chat(db):
    bot = make_bot()
    ctx = get_private_state(SQLiteStorage(), bot, 77)
    await ctx.set_state(Form.phone)
    await ctx.update_data(a=1)
    assert await SQLiteStorage().get_state(key(77, bot_id=bot.id)) == Form.phone.state
    assert await ctx.get_data() == {"a": 1}


# ------------------------------------------------------------------ main.py (webhook)

WEB_SECRET = "s" * 32
UPDATE = {
    "update_id": 1,
    "edited_channel_post": {"message_id": 1, "date": 1700000000, "chat": {"id": -5, "type": "channel", "title": "C"}},
}


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TestClient]:
    monkeypatch.setattr(main, "WEBHOOK_SECRET", WEB_SECRET)
    monkeypatch.setattr(main, "WEBHOOK_PATH", "/webhook")
    dp = Dispatcher()

    @dp.edited_channel_post()
    async def handler(post) -> None:  # tarmoqqa chiqmaydigan update turi
        pass

    c = TestClient(TestServer(main.build_web_app(dp)))
    await c.start_server()
    yield c
    await c.close()


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status == 200 and await resp.json() == {"ok": True}


async def test_webhook_rejects_missing_secret(client):
    assert (await client.post("/webhook", json=UPDATE)).status == 401


@pytest.mark.parametrize("secret", ["wrong", "", WEB_SECRET[:-1], WEB_SECRET + "x", WEB_SECRET.upper()])
async def test_webhook_rejects_wrong_secret(client, secret):
    resp = await client.post("/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": secret})
    assert resp.status == 401


async def test_webhook_accepts_correct_secret(client):
    resp = await client.post("/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": WEB_SECRET})
    assert resp.status == 200


async def test_only_post_to_known_path(client):
    assert (await client.get("/webhook")).status == 405
    assert (await client.post("/other", json=UPDATE)).status == 404


def test_module_wires_expected_routers():
    from handlers import errors, get_routers

    routers = get_routers()
    assert len(routers) == len({id(r) for r in routers}) == 13
    assert routers[0] is errors.router  # errors birinchi: boshqa routerlardagi xatolar ham unga tushadi
    for r in routers:
        r._parent_router = None
