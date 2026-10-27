import os
import sys
import tempfile

# Loyiha modullari import qilinishidan OLDIN: config.py .env ni yuklaydi, lekin allaqachon o'rnatilgan
# o'zgaruvchilarni bosmaydi. Shunda test hech qachon haqiqiy sirlar/sozlamalardan foydalanmaydi.
_TMP = tempfile.mkdtemp(prefix="creativ-bot-tests-")
os.environ.update(
    {
        "BOT_TOKEN": "123456:TESTTOKEN",
        "ADMIN_IDS": "1001,1002",
        "DEVELOPER_IDS": "9001",
        "VOTING_MINUTES": "10",
        "VOTE_ACCEPT_PERCENT": "60",
        "AUTO_DELETE_SECONDS": "120",
        "REJOIN_COOLDOWN_SECONDS": "0",
        "API_URL": "https://ai.invalid/v1/chat/completions",
        "API_TOKEN": "test-token",
        "API_MODEL": "test-model",
        "WEBHOOK_URL": "",
        "WEBHOOK_PATH": "",
        "WEBHOOK_SECRET": "",
        "WEB_HOST": "",
        "WEB_PORT": "",
        "DATA_DIR": _TMP,
        "LOG_LEVEL": "WARNING",
    }
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from aiogram import Dispatcher  # noqa: E402

import database  # noqa: E402
from tests.telegram_fakes import FakeSession, make_bot  # noqa: E402


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    """Har bir test uchun toza SQLite bazasi."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setattr(database, "_conn", None)
    await database.init_db()
    yield database
    await database.close_db()


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Modullardagi xotira keshlari testlar orasida sizib o'tmasin."""
    from handlers import ai, errors
    from utils import autodelete, members

    def clear():
        members._seen.clear()
        ai._last_ask.clear()
        ai._ai_messages.clear()
        errors._last_alert.clear()
        autodelete._tasks.clear()

    clear()
    yield
    clear()


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def bot(session):
    return make_bot(session)


@pytest_asyncio.fixture
async def dp(db):
    """To'liq dispatcher: haqiqiy routerlar, SQLite FSM, a'zolarni kuzatuvchi middleware."""
    from handlers import get_routers
    from utils.fsm_storage import SQLiteStorage
    from utils.form_expiry import FormExpiryMiddleware
    from utils.members import TrackMembersMiddleware

    routers = get_routers()
    dispatcher = Dispatcher(storage=SQLiteStorage())
    dispatcher.message.outer_middleware(TrackMembersMiddleware())
    dispatcher.message.outer_middleware(FormExpiryMiddleware())
    dispatcher.include_routers(*routers)
    yield dispatcher
    # routerlar modul darajasidagi singleton: keyingi test uchun dispatcherdan ajratamiz
    for router in routers:
        router._parent_router = None


@pytest.fixture(autouse=True)
def _fast_typing(monkeypatch):
    """Savollar orasidagi sun'iy kechikish testni sekinlashtirmasin."""
    import utils.typing as typing_mod

    real = typing_mod.send_typing

    async def quick(bot, chat_id, text, delay=1.0, **kwargs):
        return await real(bot, chat_id, text, delay=0, **kwargs)

    monkeypatch.setattr(typing_mod, "send_typing", quick)
    import utils.questions as questions

    monkeypatch.setattr(questions, "send_typing", quick)


async def expire_voting(app_id: int) -> None:
    """Ovoz berish muddatini o'tgan qilib qo'yadi."""
    db = await database.get_db()
    await db.execute(
        "UPDATE applications SET voting_ends_at = datetime('now', '-1 minute') WHERE id = ?", (app_id,)
    )
    await db.commit()


async def age_application(app_id: int, days: int) -> None:
    db = await database.get_db()
    await db.execute(
        "UPDATE applications SET created_at = datetime('now', ?) WHERE id = ?", (f"-{days} days", app_id)
    )
    await db.commit()
