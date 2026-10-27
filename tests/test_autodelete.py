"""utils/autodelete.py: guruhdagi bot xabarlarini kechiktirib o'chirish (bot qayta ishga tushsa ham)."""
import asyncio
import time
from typing import Callable

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import database as dbm
from keyboards.vote import vote_inline
from tests import telegram_fakes as tf
from utils import autodelete
from utils.autodelete import AutoDeleteMiddleware, keep_messages, restore_pending_deletes, schedule_delete

G = tf.GROUP_ID
OTHER_MARKUP = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="x", callback_data="other:1")]])


@pytest.fixture
def delete_after(monkeypatch) -> Callable[[float], None]:
    def _set(seconds: float) -> None:
        monkeypatch.setattr(autodelete, "AUTO_DELETE_SECONDS", seconds)

    return _set


async def drain() -> None:
    """Fon vazifalari tugashini kutadi."""
    while autodelete._tasks:
        await asyncio.gather(*list(autodelete._tasks), return_exceptions=True)


async def cancel_tasks() -> None:
    for t in list(autodelete._tasks):
        t.cancel()
    await asyncio.gather(*autodelete._tasks, return_exceptions=True)


@pytest.fixture
def mw_bot(session, bot) -> Bot:
    bot.session.middleware(AutoDeleteMiddleware())
    return bot


class TestScheduling:
    async def test_group_message_is_queued_and_deleted(self, db, mw_bot, session, delete_after):
        delete_after(0.05)
        sent = await mw_bot.send_message(G, "salom")
        rows = await dbm.get_pending_deletes()
        assert [(r["chat_id"], r["message_id"]) for r in rows] == [(G, sent.message_id)]
        await drain()
        assert [m.message_id for m in session.of(DeleteMessage)] == [sent.message_id]
        assert await dbm.get_pending_deletes() == []

    @pytest.mark.parametrize("seconds,chat,markup", [
        (0.01, 42, None),                       # shaxsiy chat
        (0, G, None),                           # o'chirilgan sozlama
        (0.01, G, vote_inline(7)),              # ovoz xabari (utils/voting o'zi o'chiradi)
    ])
    async def test_never_queued(self, db, mw_bot, session, delete_after, seconds, chat, markup):
        delete_after(seconds)
        await mw_bot.send_message(chat, "matn", reply_markup=markup)
        assert await dbm.get_pending_deletes() == [] and not autodelete._tasks

    async def test_other_inline_keyboards_are_deleted(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        await mw_bot.send_message(G, "boshqa", reply_markup=OTHER_MARKUP)
        assert len(await dbm.get_pending_deletes()) == 1
        await drain()

    async def test_keep_messages_protects_ai_answers_and_resets_even_on_error(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        with keep_messages():
            await mw_bot.send_message(G, "AI javobi")
        with pytest.raises(RuntimeError), keep_messages():
            raise RuntimeError
        await mw_bot.send_message(G, "oddiy")
        assert len(await dbm.get_pending_deletes()) == 1  # faqat "oddiy"
        await drain()

    async def test_keep_flag_is_isolated_between_concurrent_tasks(self, db, mw_bot, session, delete_after):
        delete_after(0.3)  # tekshiruvdan oldin o'chirish ishga tushib ketmasin (poyga bo'lmasligi uchun)

        async def kept() -> None:
            with keep_messages():
                await asyncio.sleep(0.02)
                await mw_bot.send_message(G, "saqlanadi")

        async def normal() -> None:
            await asyncio.sleep(0.01)
            await mw_bot.send_message(G, "o'chadi")

        await asyncio.gather(kept(), normal())
        assert len(await dbm.get_pending_deletes()) == 1
        await drain()

    async def test_only_successful_send_message_is_tracked(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        await mw_bot.get_chat_member_count(G)
        session.errors[SendMessage] = tf.bad_request("Bad Request", SendMessage(chat_id=G, text="x"))
        with pytest.raises(TelegramBadRequest):
            await mw_bot.send_message(G, "x")
        assert await dbm.get_pending_deletes() == []


class TestDeletionOutcomes:
    @pytest.mark.parametrize("error", [tf.bad_request("Bad Request: message to delete not found"), tf.forbidden()])
    async def test_delete_failure_is_logged_and_row_removed(self, db, bot, session, error, caplog):
        session.errors[DeleteMessage] = error
        await dbm.add_pending_delete(G, 5, int(time.time()) - 1)
        await restore_pending_deletes(bot)
        await drain()
        assert await dbm.get_pending_deletes() == []
        assert any("o'chirib bo'lmadi" in r.message for r in caplog.records)

    async def test_cancelled_task_keeps_row_for_next_start(self, db, bot, session):
        await dbm.add_pending_delete(G, 5, int(time.time()) + 3600)
        await restore_pending_deletes(bot)
        await cancel_tasks()
        assert len(await dbm.get_pending_deletes()) == 1 and not session.of(DeleteMessage)


class TestRestore:
    async def test_overdue_rows_are_deleted_immediately(self, db, bot, session):
        await dbm.add_pending_delete(G, 1, int(time.time()) - 500)
        await dbm.add_pending_delete(G, 2, int(time.time()) - 5)
        await restore_pending_deletes(bot)
        await drain()
        assert sorted(m.message_id for m in session.of(DeleteMessage)) == [1, 2]
        assert await dbm.get_pending_deletes() == []

    async def test_future_rows_wait_for_their_time(self, db, bot, session):
        await dbm.add_pending_delete(G, 1, int(time.time()) + 3600)
        await restore_pending_deletes(bot)
        await asyncio.sleep(0.05)
        assert not session.of(DeleteMessage) and len(autodelete._tasks) == 1
        await cancel_tasks()

    async def test_nothing_to_restore_and_disabled_schedule_is_a_noop(self, db, bot, session, delete_after):
        await restore_pending_deletes(bot)
        delete_after(0)
        await schedule_delete(bot, G, 1)
        assert not autodelete._tasks and await dbm.get_pending_deletes() == []
