"""main.py: webhook rejimi (maxfiy token, /health) va ishga tushirish yordamchilari."""
import pytest
from aiogram import Dispatcher
from aiohttp.test_utils import TestClient, TestServer

import main

SECRET = "s" * 32


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(main, "WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(main, "WEBHOOK_PATH", "/webhook")
    seen = []
    dp = Dispatcher()

    @dp.edited_channel_post()
    async def handler(post):  # tarmoqqa chiqmaydigan update turi
        seen.append(post)

    app = main.build_web_app(dp)
    c = TestClient(TestServer(app))
    await c.start_server()
    c.seen = seen
    yield c
    await c.close()


UPDATE = {
    "update_id": 1,
    "edited_channel_post": {"message_id": 1, "date": 1700000000, "chat": {"id": -5, "type": "channel", "title": "C"}},
}


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status == 200 and await resp.json() == {"ok": True}


async def test_webhook_rejects_missing_secret(client):
    assert (await client.post("/webhook", json=UPDATE)).status == 401


@pytest.mark.parametrize("secret", ["wrong", "", SECRET[:-1], SECRET + "x", SECRET.upper()])
async def test_webhook_rejects_wrong_secret(client, secret):
    resp = await client.post("/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": secret})
    assert resp.status == 401


async def test_webhook_accepts_correct_secret(client):
    resp = await client.post("/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
    assert resp.status == 200


async def test_webhook_only_accepts_post(client):
    assert (await client.get("/webhook")).status == 405


async def test_unknown_path_is_404(client):
    assert (await client.post("/other", json=UPDATE)).status == 404


def test_module_wires_expected_routers_and_helpers():
    from handlers import get_routers

    routers = get_routers()
    assert len(routers) == len({id(r) for r in routers}) == 13
    # errors router birinchi: boshqa routerlardagi xatolar ham unga tushadi
    import handlers.errors as errors

    assert get_routers()[0] is errors.router
    for r in get_routers():
        r._parent_router = None
