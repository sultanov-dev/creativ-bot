"""utils/expiry.py (3 kundan beri ko'rilmagan arizalar, fon tsikli) va ariza muddatlari: qayta ariza kutishi, yetim ovoz xabari, ma'lumotlarni o'chirish, status migratsiyasi."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from tests.table import check
from aiogram import Bot
from aiogram.methods import (
    DeclineChatJoinRequest,
    DeleteMessage,
    EditMessageText,
    SendMessage,
)

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import age_application
from tests.flow import (
    admin_accept,
    feed,
    get_app,
    make_voting_app,
    start_application,
    status_of,
)
from utils import expiry
from utils.timefmt import format_deadline, format_wait

G = tf.GROUP_ID
U = 1


async def make_app(
    user: int = 1, age_days: int = 0, vote_message_id: int | None = None
) -> int:
    """`pending` ariza (kerak bo'lsa eskirgan va ovoz xabari bilan)."""
    app_id = await dbm.create_application(user, G, "Aziz Karimov", "ANKETA\n")
    assert app_id is not None
    if vote_message_id:
        await dbm.set_vote_message(app_id, vote_message_id)
    if age_days:
        await age_application(app_id, age_days)
    return app_id


async def age_decision(app_id: int, interval: str = "-3 minutes") -> None:
    d = await dbm.get_db()
    await d.execute(
        "UPDATE applications SET decided_at = datetime('now', ?) WHERE id = ?",
        (interval, app_id),
    )
    await d.commit()


class TestExpireApplications:
    async def test_old_pending_is_expired_and_applicant_notified(
        self, db, bot, session
    ):
        a = await make_app(age_days=4)
        assert await expiry.expire_applications(bot) == 1
        assert await status_of(a) == "expired"
        assert session.of(DeclineChatJoinRequest)[0].user_id == 1
        assert "3 kun ichida ko'rib chiqilmadi" in session.texts_to(1)[0]
        assert not session.of(
            EditMessageText
        )  # ovoz xabari yo'q: tahrirlanadigan narsa ham yo'q
        session.clear()
        assert (
            await expiry.expire_applications(bot) == 0 and session.requests == []
        )  # qayta ishlanmaydi
        assert (
            await dbm.create_application(1, G, "Aziz Karimov", "x\n") is not None
        )  # qayta ariza berish mumkin

    async def test_vote_message_is_edited_when_present(self, db, bot, session):
        await make_app(age_days=4, vote_message_id=88)
        await expiry.expire_applications(bot)
        edit = session.of(EditMessageText)[0]
        assert edit.message_id == 88 and "yopildi" in edit.text

    async def test_recent_pending_and_voting_are_left_alone(self, db, bot, session):
        recent = await make_app(user=1, age_days=2)
        voting_app = await make_app(
            user=2, age_days=10
        )  # ovoz berish: yakunlovchining ishi
        await dbm.start_voting(voting_app, 10)
        assert await expiry.expire_applications(bot) == 0
        assert (
            await status_of(recent) == "pending"
            and await status_of(voting_app) == "voting"
        )
        assert session.requests == []

    async def test_admin_decision_expires_after_days_without_admin_decision(
        self, db, bot, session
    ):
        a = await make_app()
        await dbm.start_voting(a, 10)
        await dbm.change_status(a, "voting", "admin_decision")
        d = await dbm.get_db()
        await d.execute(
            "UPDATE applications SET voting_ends_at = datetime('now', '-4 days') WHERE id = ?",
            (a,),
        )
        await d.commit()
        assert await expiry.expire_applications(bot) == 1
        assert await status_of(a) == "expired"

    async def test_finished_applications_are_ignored(self, db, bot, session):
        finals = ["accepted", "rejected", "expired", "failed"]
        apps = []
        for user, final in enumerate(finals, start=1):
            a = await make_app(user=user, age_days=10)
            await dbm.change_status(a, "pending", final)
            apps.append(a)
        assert await expiry.expire_applications(bot) == 0
        assert [await status_of(a) for a in apps] == finals

    async def test_status_changed_meanwhile_is_skipped(
        self, db, bot, session, monkeypatch
    ):
        a = await make_app(age_days=4)
        real = dbm.get_expired_applications

        async def stale(days: int):
            rows = await real(days)
            await dbm.change_status(
                a, "pending", "rejected"
            )  # admin shu orada rad etdi
            return rows

        monkeypatch.setattr(expiry, "get_expired_applications", stale)
        assert await expiry.expire_applications(bot) == 0
        assert await status_of(a) == "rejected" and session.requests == []

    async def test_telegram_errors_do_not_abort_the_batch(self, db, bot, session):
        session.errors[DeclineChatJoinRequest] = tf.bad_request(
            "HIDE_REQUESTER_MISSING"
        )
        session.errors[EditMessageText] = tf.bad_request("message not found")
        session.errors[SendMessage] = lambda m: (
            tf.forbidden(m) if m.chat_id == 1 else None
        )  # 1-foydalanuvchi botni bloklagan
        a = await make_app(user=1, age_days=4, vote_message_id=1)
        b = await make_app(user=2, age_days=4, vote_message_id=2)
        assert await expiry.expire_applications(bot) == 2
        assert await status_of(a) == await status_of(b) == "expired"


class TestLoop:
    async def _run(
        self, bot: Bot, monkeypatch: pytest.MonkeyPatch, iterations: int
    ) -> int:
        """Tsiklni `iterations` aylanishdan keyin to'xtatadi; aylanishlar sonini qaytaradi."""
        ticks = {"n": 0}

        async def fake_sleep(_: float) -> None:
            ticks["n"] += 1
            if ticks["n"] >= iterations:
                raise asyncio.CancelledError

        monkeypatch.setattr(expiry.asyncio, "sleep", fake_sleep)
        with pytest.raises(asyncio.CancelledError):
            await expiry.run_expiry_loop(bot)
        return ticks["n"]

    def _jobs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        calls: list[str],
        *,
        boom: str | None = None,
    ) -> None:
        """Ikkala ish ham chaqiruvni yozadi; `boom` nomlisi RuntimeError beradi."""

        def make(name: str) -> Callable[[Bot], Awaitable[int]]:
            async def job(b: Bot) -> int:
                calls.append(name)
                if name == boom:
                    raise RuntimeError("db locked")
                return 0

            return job

        monkeypatch.setattr(expiry, "expire_applications", make("expire"))
        monkeypatch.setattr(expiry, "finalize_due_votings", make("finalize"))

    async def test_loop_runs_both_jobs_each_cycle(self, db, bot, monkeypatch):
        calls: list[str] = []
        self._jobs(monkeypatch, calls)
        assert await self._run(bot, monkeypatch, 3) == 3
        assert calls == ["expire", "finalize"] * 3
        assert expiry.CHECK_INTERVAL == 15 and expiry.EXPIRE_DAYS == 3

    @pytest.mark.parametrize(
        "boom,expected",
        [("expire", ["expire"] * 3), ("finalize", ["expire", "finalize"] * 3)],
    )
    async def test_loop_survives_exceptions(
        self, db, bot, monkeypatch, caplog, boom, expected
    ):
        """expire yiqilsa shu aylanishda finalize chaqirilmaydi; finalize yiqilsa tsikl davom etadi."""
        calls: list[str] = []
        self._jobs(monkeypatch, calls, boom=boom)
        await self._run(bot, monkeypatch, 3)
        assert calls == expected
        assert any("xatolik" in r.message for r in caplog.records)

    async def test_loop_actually_processes_due_votings(
        self, db, bot, session, monkeypatch
    ):
        a = await make_voting_app(votes=["yes"])
        await self._run(bot, monkeypatch, 1)
        assert await status_of(a) == "accepted"


class TestFormatting:
    def test_wait_and_deadline_texts(self):
        check(format_wait, [(45, "45 soniya"), (60, "1 daqiqa"), (80, "1 daqiqa 20 soniya"), (0, "1 soniya")])
        check(format_deadline, [(10, "10 daqiqada"), (90, "90 daqiqada"), (120, "2 soatda"), (2880, "2 kunda")])

    async def test_vote_message_states_deadline_from_config(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.clear()
        await admin_accept(dp, bot, app_id)
        assert "⏳ Ovoz berish 10 daqiqada tugaydi." in session.sent_to(G)[0].text


class TestCooldown:
    @pytest.fixture(autouse=True)
    def cooldown(self, monkeypatch):
        import handlers.join

        monkeypatch.setattr(handlers.join, "REJOIN_COOLDOWN_SECONDS", 120)

    @pytest.mark.parametrize("status", ["rejected", "expired", "failed"])
    async def test_rejoin_inside_cooldown_is_refused_with_time(
        self, dp, bot, session, status
    ):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", status)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert (
            len(sent) == 1
            and "kuting" in sent[0]
            and ("daqiqa" in sent[0] or "soniya" in sent[0])
        )
        assert [(m.chat_id, m.user_id) for m in session.of(DeclineChatJoinRequest)] == [
            (G, U)
        ]

    async def test_after_cooldown_questionnaire_starts(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "rejected")
        await age_decision(app_id, "-3 minutes")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [
            texts.REJOIN_AFTER_REJECTION,
            texts.ASK_FULL_NAME,
        ]
        assert not session.of(DeclineChatJoinRequest)

    async def test_rejoin_wait_seconds(self, db):
        assert await dbm.rejoin_wait_seconds(5, G, 120) == 0  # yangi foydalanuvchi
        accepted = await dbm.create_application(2, G, "A B", "x\n")
        assert accepted is not None
        await dbm.change_status(accepted, "pending", "accepted")
        assert await dbm.rejoin_wait_seconds(2, G, 120) == 0
        rejected = await dbm.create_application(U, G, "A B", "x\n")
        assert rejected is not None
        await dbm.change_status(rejected, "pending", "rejected")
        assert await dbm.rejoin_wait_seconds(U, G, 0) == 0  # 0 o'chiradi
        assert 0 < await dbm.rejoin_wait_seconds(U, G, 120) <= 120


class TestOrphanVoteMessage:
    async def test_only_voting_without_message_goes_back_to_pending(self, db):
        orphan = await make_app(user=1)
        await dbm.start_voting(orphan, 10)
        kept = await make_app(user=2)
        await dbm.start_voting(kept, 10)
        await dbm.set_vote_message(kept, 55)
        assert await dbm.reset_orphan_votings() == 1
        app = await get_app(orphan)
        assert app["status"] == "pending" and app["voting_ends_at"] is None
        assert await status_of(kept) == "voting"

    async def test_failed_message_id_write_deletes_message_and_reverts(
        self, dp, bot, session, monkeypatch
    ):
        import utils.applications as apps

        app_id = await start_application(dp, bot)

        async def boom(**kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(apps, "set_vote_message", boom)
        session.clear()
        assert await apps.open_voting(bot, await get_app(app_id)) is False
        assert await status_of(app_id) == "pending" and session.of(DeleteMessage)


class TestRetention:
    async def _old(self, user: int, status: str, interval: str = "-40 days") -> int:
        """Yakunlangan ariza + saqlangan profil, qaror vaqti `interval` oldin."""
        a = await dbm.create_application(
            user, G, "A B", "anketa\n", phone="+998901234567"
        )
        assert a is not None
        await dbm.save_profile(user, {"phone": "+998901234567"})
        await dbm.change_status(
            a, "pending", "accepted" if status == "removed" else status
        )
        if status == "removed":  # admin chiqarib yuborgan a'zo
            await dbm.mark_removed(user, G)
        await age_decision(a, interval)
        return a

    @pytest.mark.parametrize("status", ["rejected", "expired", "failed", "removed"])
    async def test_old_data_is_deleted_with_votes_and_profile(self, db, status):
        a = await self._old(U, status)
        d = await dbm.get_db()
        await d.execute(
            "INSERT INTO votes (application_id, voter_id, vote, reason) VALUES (?, 9, 'no', 'sabab')",
            (a,),
        )
        await d.commit()
        assert await dbm.purge_old_data(30) == 1
        assert await dbm.get_application(a) is None and await dbm.get_profile(U) is None
        row = await (await d.execute("SELECT COUNT(*) FROM votes")).fetchone()
        assert row is not None and row[0] == 0

    async def test_recent_accepted_and_zero_days_are_kept(self, db):
        recent = await self._old(1, "rejected", "-5 days")
        member = await self._old(2, "accepted", "-400 days")
        ancient = await self._old(3, "rejected", "-4000 days")
        assert await dbm.purge_old_data(30) == 1  # faqat 3-foydalanuvchining eskisi
        assert (
            await dbm.get_application(recent) is not None
            and await dbm.get_profile(1) is not None
        )
        assert await dbm.get_application(member) is not None
        assert await dbm.get_application(ancient) is None
        keep = await self._old(4, "rejected", "-4000 days")
        assert (
            await dbm.purge_old_data(0) == 0
            and await dbm.get_application(keep) is not None
        )  # 0 o'chiradi

    async def test_profile_stays_if_user_has_other_application(self, db):
        await self._old(U, "rejected")
        fresh = await dbm.create_application(U, G, "A B", "again\n")
        assert fresh is not None
        assert await dbm.purge_old_data(30) == 1
        assert (
            await dbm.get_application(fresh) is not None
            and await dbm.get_profile(U) is not None
        )

    async def test_after_purge_user_starts_clean(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "rejected")
        await age_decision(app_id, "-40 days")
        await dbm.purge_old_data(30)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U)[-1] == texts.ASK_FULL_NAME


class TestStatusRenameMigration:
    async def test_old_creator_review_becomes_admin_decision(self, db):
        a = await make_app()
        d = await dbm.get_db()
        await d.execute(
            "UPDATE applications SET status = 'creator_review' WHERE id = ?", (a,)
        )
        await d.commit()
        await dbm.init_db()
        assert await status_of(a) == "admin_decision"
        # indeks yangilandi: shu foydalanuvchiga ikkinchi faol ariza ochilmaydi
        assert await dbm.create_application(U, G, "A B", "y\n") is None
