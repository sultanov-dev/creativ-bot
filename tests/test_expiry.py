"""utils/expiry.py: 3 kundan beri ko'rilmagan arizalarni yopish va fon tsikli."""
import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeclineChatJoinRequest, EditMessageText, SendMessage

import database as dbm
from tests import telegram_fakes as tf
from tests.conftest import age_application, expire_voting
from utils import expiry

G = tf.GROUP_ID


async def app(user=1, age_days=0, vote_message_id=None):
    app_id = await dbm.create_application(user, G, "Aziz Karimov", "ANKETA\n")
    if vote_message_id:
        await dbm.set_vote_message(app_id, vote_message_id)
    if age_days:
        await age_application(app_id, age_days)
    return app_id


async def status(app_id):
    return (await dbm.get_application(app_id))["status"]


class TestExpireApplications:
    async def test_old_pending_is_expired_and_applicant_notified(self, db, bot, session):
        a = await app(age_days=4)
        assert await expiry.expire_applications(bot) == 1
        assert await status(a) == "expired"
        assert session.of(DeclineChatJoinRequest)[0].user_id == 1
        assert "3 kun ichida ko'rib chiqilmadi" in session.texts_to(1)[0]

    async def test_recent_pending_is_kept(self, db, bot, session):
        a = await app(age_days=2)
        assert await expiry.expire_applications(bot) == 0
        assert await status(a) == "pending" and session.requests == []

    async def test_vote_message_is_edited_when_present(self, db, bot, session):
        await app(age_days=4, vote_message_id=88)
        await expiry.expire_applications(bot)
        edit = session.of(EditMessageText)[0]
        assert edit.message_id == 88 and "yopildi" in edit.text

    async def test_no_edit_without_vote_message(self, db, bot, session):
        await app(age_days=4)
        await expiry.expire_applications(bot)
        assert not session.of(EditMessageText)

    async def test_creator_review_expires_after_days_without_admin_decision(self, db, bot, session):
        a = await app()
        await dbm.start_voting(a, 10)
        await dbm.change_status(a, "voting", "creator_review")
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET voting_ends_at = datetime('now', '-4 days') WHERE id = ?", (a,))
        await d.commit()
        assert await expiry.expire_applications(bot) == 1
        assert await status(a) == "expired"

    async def test_voting_applications_are_left_to_finalizer(self, db, bot, session):
        a = await app(age_days=10)
        await dbm.start_voting(a, 10)
        assert await expiry.expire_applications(bot) == 0
        assert await status(a) == "voting"

    @pytest.mark.parametrize("final", ["accepted", "rejected", "expired", "failed"])
    async def test_finished_applications_are_ignored(self, db, bot, session, final):
        a = await app(age_days=10)
        await dbm.change_status(a, "pending", final)
        assert await expiry.expire_applications(bot) == 0
        assert await status(a) == final

    async def test_expired_user_can_apply_again(self, db, bot, session):
        await app(age_days=4)
        await expiry.expire_applications(bot)
        assert await dbm.create_application(1, G, "Aziz Karimov", "x\n") is not None

    async def test_status_changed_meanwhile_is_skipped(self, db, bot, session, monkeypatch):
        a = await app(age_days=4)
        real = dbm.get_expired_applications

        async def stale(days):
            rows = await real(days)
            await dbm.change_status(a, "pending", "rejected")  # admin shu orada rad etdi
            return rows

        monkeypatch.setattr(expiry, "get_expired_applications", stale)
        assert await expiry.expire_applications(bot) == 0
        assert await status(a) == "rejected" and session.requests == []

    async def test_telegram_errors_do_not_abort_the_batch(self, db, bot, session):
        session.errors[DeclineChatJoinRequest] = TelegramBadRequest(method=None, message="HIDE_REQUESTER_MISSING")
        session.errors[EditMessageText] = TelegramBadRequest(method=None, message="message not found")
        a = await app(user=1, age_days=4, vote_message_id=1)
        b = await app(user=2, age_days=4, vote_message_id=2)
        assert await expiry.expire_applications(bot) == 2
        assert await status(a) == await status(b) == "expired"

    async def test_blocked_user_does_not_abort_the_batch(self, db, bot, session):
        from aiogram.exceptions import TelegramForbiddenError

        session.errors[SendMessage] = lambda m: TelegramForbiddenError(method=m, message="Forbidden") \
            if m.chat_id == 1 else None
        await app(user=1, age_days=4)
        b = await app(user=2, age_days=4)
        assert await expiry.expire_applications(bot) == 2 and await status(b) == "expired"

    async def test_idempotent(self, db, bot, session):
        await app(age_days=4)
        await expiry.expire_applications(bot)
        session.clear()
        assert await expiry.expire_applications(bot) == 0 and session.requests == []


class TestLoop:
    async def _run(self, bot, monkeypatch, iterations, *, boom=None):
        ticks = {"n": 0}

        async def fake_sleep(_):
            ticks["n"] += 1
            if ticks["n"] >= iterations:
                raise asyncio.CancelledError

        monkeypatch.setattr(expiry.asyncio, "sleep", fake_sleep)
        with pytest.raises(asyncio.CancelledError):
            await expiry.run_expiry_loop(bot)
        return ticks["n"]

    async def test_loop_runs_both_jobs_each_cycle(self, db, bot, monkeypatch):
        calls = []

        async def expire(b):
            calls.append("expire")

        async def finalize(b):
            calls.append("finalize")

        monkeypatch.setattr(expiry, "expire_applications", expire)
        monkeypatch.setattr(expiry, "finalize_due_votings", finalize)
        assert await self._run(bot, monkeypatch, 3) == 3
        assert calls == ["expire", "finalize"] * 3

    async def test_loop_survives_exceptions(self, db, bot, monkeypatch, caplog):
        runs = []

        async def expire(b):
            runs.append(1)
            raise RuntimeError("db locked")

        async def finalize(b):
            raise AssertionError("expire yiqilgach finalize shu aylanishda chaqirilmaydi")

        monkeypatch.setattr(expiry, "expire_applications", expire)
        monkeypatch.setattr(expiry, "finalize_due_votings", finalize)
        await self._run(bot, monkeypatch, 3)
        assert len(runs) == 3
        assert any("xatolik" in r.message for r in caplog.records)

    async def test_finalizer_error_does_not_kill_loop(self, db, bot, monkeypatch):
        runs = []

        async def finalize(b):
            runs.append(1)
            raise RuntimeError("x")

        async def expire(b):
            return 0

        monkeypatch.setattr(expiry, "expire_applications", expire)
        monkeypatch.setattr(expiry, "finalize_due_votings", finalize)
        await self._run(bot, monkeypatch, 3)
        assert len(runs) == 3

    async def test_loop_actually_processes_due_votings(self, db, bot, session, monkeypatch):
        a = await dbm.create_application(1, G, "A B", "x\n")
        await dbm.start_voting(a, 10)
        await dbm.add_vote(a, 100, "yes")
        await expire_voting(a)
        await self._run(bot, monkeypatch, 1)
        assert await status(a) == "accepted"

    async def test_check_interval_is_one_minute(self):
        assert expiry.CHECK_INTERVAL == 60 and expiry.EXPIRE_DAYS == 3
