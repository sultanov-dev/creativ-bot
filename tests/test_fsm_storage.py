"""utils/fsm_storage.py + utils/fsm.py: FSM holati bot qayta ishga tushsa ham saqlanishi kerak."""
from aiogram.fsm.storage.base import StorageKey

import database
from states import Form
from utils.fsm import get_private_state
from utils.fsm_storage import SQLiteStorage

from tests.telegram_fakes import make_bot


def key(user=1, chat=None, bot_id=123456):
    return StorageKey(bot_id=bot_id, chat_id=user if chat is None else chat, user_id=user)


async def test_state_roundtrip_with_state_object_and_string(db):
    s = SQLiteStorage()
    assert await s.get_state(key()) is None
    await s.set_state(key(), Form.age)
    assert await s.get_state(key()) == Form.age.state
    await s.set_state(key(), "custom:state")
    assert await s.get_state(key()) == "custom:state"


async def test_clearing_state_deletes_row(db):
    s = SQLiteStorage()
    await s.set_state(key(), Form.age)
    await s.set_state(key(), None)
    assert await s.get_state(key()) is None
    d = await database.get_db()
    assert (await (await d.execute("SELECT COUNT(*) FROM fsm")).fetchone())[0] == 0


async def test_data_roundtrip_and_empty(db):
    s = SQLiteStorage()
    assert await s.get_data(key()) == {}
    await s.set_data(key(), {"a": 1, "b": "ўзбек"})
    assert await s.get_data(key()) == {"a": 1, "b": "ўзбек"}
    await s.set_data(key(), {})
    assert await s.get_data(key()) == {}


async def test_keys_are_isolated_per_user_and_chat(db):
    s = SQLiteStorage()
    await s.set_data(key(1), {"u": 1})
    await s.set_data(key(2), {"u": 2})
    await s.set_data(key(1, chat=-5), {"u": "group"})
    assert (await s.get_data(key(1)))["u"] == 1
    assert (await s.get_data(key(2)))["u"] == 2
    assert (await s.get_data(key(1, chat=-5)))["u"] == "group"


async def test_state_and_data_do_not_collide(db):
    s = SQLiteStorage()
    await s.set_state(key(), Form.job)
    await s.set_data(key(), {"x": 1})
    await s.set_state(key(), None)
    assert await s.get_data(key()) == {"x": 1}


async def test_survives_connection_restart(db):
    s = SQLiteStorage()
    await s.set_state(key(), Form.about)
    await s.set_data(key(), {"full_name": "A B"})
    await database.close_db()
    assert await SQLiteStorage().get_state(key()) == Form.about.state
    assert await SQLiteStorage().get_data(key()) == {"full_name": "A B"}


async def test_close_is_a_noop(db):
    await SQLiteStorage().close()


async def test_get_private_state_uses_user_as_chat(db):
    bot = make_bot()
    ctx = get_private_state(SQLiteStorage(), bot, 77)
    await ctx.set_state(Form.phone)
    await ctx.update_data(a=1)
    assert await SQLiteStorage().get_state(key(77, bot_id=bot.id)) == Form.phone.state
    assert await ctx.get_data() == {"a": 1}
