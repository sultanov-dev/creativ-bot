"""utils/autodelete.py: guruhdagi bot xabarlarini kechiktirib o'chirish (bot qayta ishga tushsa ham)."""
import asyncio
import time

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import DeleteMessage, SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import database as dbm
from keyboards.vote import vote_inline
from tests import telegram_fakes as tf
from utils import autodelete
from utils.autodelete import AutoDeleteMiddleware, keep_messages, restore_pending_deletes, schedule_delete

G = tf.GROUP_ID


@pytest.fixture
def delete_after(monkeypatch):
    def _set(seconds):
        monkeypatch.setattr(autodelete, "AUTO_DELETE_SECONDS", seconds)

    return _set


async def drain():
    """Fon vazifalari tugashini kutadi."""
    while autodelete._tasks:
        await asyncio.gather(*list(autodelete._tasks), return_exceptions=True)


@pytest.fixture
def mw_bot(session, bot):
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

    async def test_private_messages_are_never_deleted(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        await mw_bot.send_message(42, "shaxsiy")
        assert await dbm.get_pending_deletes() == [] and not autodelete._tasks

    async def test_disabled_when_zero(self, db, mw_bot, session, delete_after):
        delete_after(0)
        await mw_bot.send_message(G, "salom")
        assert await dbm.get_pending_deletes() == [] and not autodelete._tasks

    async def test_vote_message_is_never_auto_deleted(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        await mw_bot.send_message(G, "ovoz", reply_markup=vote_inline(7))
        assert await dbm.get_pending_deletes() == []

    async def test_other_inline_keyboards_are_deleted(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="x", callback_data="other:1")]])
        await mw_bot.send_message(G, "boshqa", reply_markup=markup)
        assert len(await dbm.get_pending_deletes()) == 1
        await drain()

    async def test_keep_messages_context_protects_ai_answers(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        with keep_messages():
            await mw_bot.send_message(G, "AI javobi")
        await mw_bot.send_message(G, "oddiy")
        assert len(await dbm.get_pending_deletes()) == 1  # faqat "oddiy"
        await drain()

    async def test_keep_flag_is_reset_after_context_even_on_error(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        with pytest.raises(RuntimeError):
            with keep_messages():
                raise RuntimeError
        await mw_bot.send_message(G, "keyin")
        assert len(await dbm.get_pending_deletes()) == 1
        await drain()

    async def test_keep_flag_is_isolated_between_concurrent_tasks(self, db, mw_bot, session, delete_after):
        delete_after(0.3)  # tekshiruvdan oldin o'chirish ishga tushib ketmasin (poyga bo'lmasligi uchun)

        async def kept():
            with keep_messages():
                await asyncio.sleep(0.02)
                await mw_bot.send_message(G, "saqlanadi")

        async def normal():
            await asyncio.sleep(0.01)
            await mw_bot.send_message(G, "o'chadi")

        await asyncio.gather(kept(), normal())
        assert len(await dbm.get_pending_deletes()) == 1
        await drain()

    async def test_only_send_message_is_tracked(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        await mw_bot.get_chat_member_count(G)
        assert await dbm.get_pending_deletes() == []

    async def test_failed_send_schedules_nothing(self, db, mw_bot, session, delete_after):
        delete_after(0.01)
        session.errors[SendMessage] = TelegramBadRequest(method=None, message="Bad Request")
        with pytest.raises(TelegramBadRequest):
            await mw_bot.send_message(G, "x")
        assert await dbm.get_pending_deletes() == []


class TestDeletionOutcomes:
    @pytest.mark.parametrize("error", [
        TelegramBadRequest(method=None, message="Bad Request: message to delete not found"),
        TelegramForbiddenError(method=None, message="Forbidden: not enough rights"),
    ])
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
        task = next(iter(autodelete._tasks))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
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
        for t in list(autodelete._tasks):
            t.cancel()
        await asyncio.gather(*autodelete._tasks, return_exceptions=True)

    async def test_nothing_to_restore(self, db, bot, session):
        await restore_pending_deletes(bot)
        assert not autodelete._tasks

    async def test_schedule_delete_noop_when_disabled(self, db, bot, delete_after):
        delete_after(0)
        await schedule_delete(bot, G, 1)
        assert await dbm.get_pending_deletes() == []
