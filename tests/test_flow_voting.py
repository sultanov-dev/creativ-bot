"""Admin ko'rigi -> guruh ovozi -> natija -> adminlar qarori: butun hayot tsikli."""
import asyncio
from collections.abc import Callable

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import ApproveChatJoinRequest, DeleteMessage, SendMessage
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.flow import admin_accept, applicant_cb, assert_no_errors, cast, declined, edits, feed, get_app, last_alert, set_full_name, start_application, status_of
from tests.telegram_fakes import FakeSession
from utils.voting import finalize_due_votings

U = 1
M = [200, 201, 202, 203, 204]  # oddiy guruh a'zolari


def clear_session(bot: Bot) -> None:
    assert isinstance(bot.session, FakeSession)
    bot.session.clear()


async def voting_app(dp: Dispatcher, bot: Bot, user: int = U) -> int:
    """Admin qabul qilgan, ovoz berish ochiq ariza (sessiya tozalangan)."""
    app_id = await start_application(dp, bot, user_id=user)
    await admin_accept(dp, bot, app_id)
    clear_session(bot)
    return app_id


async def close_vote(bot: Bot, app_id: int, session: FakeSession) -> None:
    """Muddatni o'tkazib, ovozni yakunlaydi (sessiya oldin tozalanadi)."""
    await expire_voting(app_id)
    session.clear()
    await finalize_due_votings(bot)


def edit_texts(session: FakeSession) -> list[str]:
    return [e.text or "" for e in edits(session)]


def alert(session: FakeSession) -> str:
    return last_alert(session).text or ""


def inline(msg: SendMessage | object, field: str = "callback_data") -> list[str]:
    """Inline tugmalarning callback_data (yoki text) ro'yxati."""
    markup = getattr(msg, "reply_markup", None)
    assert isinstance(markup, InlineKeyboardMarkup)
    return [getattr(b, field) for row in markup.inline_keyboard for b in row]


def reply_buttons(msg: SendMessage) -> list[str]:
    assert isinstance(msg.reply_markup, ReplyKeyboardMarkup)
    return [b.text for row in msg.reply_markup.keyboard for b in row]


async def only_reason(app_id: int) -> str | None:
    """Yagona 👎 ovozning sababi."""
    return (await dbm.get_no_votes(app_id))[0]["reason"]


class TestAdminReview:
    async def test_accept_puts_application_to_group_vote(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await start_application(dp, bot)
        session.clear()
        await admin_accept(dp, bot, app_id)
        assert await status_of(app_id) == "voting"
        app = await get_app(app_id)
        group_msgs = session.sent_to(tf.GROUP_ID)
        assert len(group_msgs) == 1 and app["vote_message_id"] is not None
        assert "Yangi a'zo uchun ovoz berish" in group_msgs[0].text
        assert "+998" not in group_msgs[0].text and app["voting_ends_at"]
        # tugmalarda hisob ko'rsatilmaydi
        assert inline(group_msgs[0]) == [f"vote:yes:{app_id}", f"vote:no:{app_id}"]
        assert inline(group_msgs[0], "text") == ["👍 Ha", "👎 Yo'q"]
        assert "ovoziga qo'yildi" in session.texts_to(U)[0]
        assert any("Ovozga qo'yildi" in t for t in edit_texts(session))
        assert_no_errors(session)

    @pytest.mark.parametrize("clicker", [555, U], ids=["non_admin", "applicant"])
    async def test_only_admins_can_accept_or_reject(self, dp: Dispatcher, bot: Bot, session: FakeSession, clicker: int) -> None:
        app_id = await start_application(dp, bot)
        for action in ("accept", "reject"):
            await feed(dp, bot, tf.callback(clicker, applicant_cb(action, app_id)))
            assert "faqat adminlar" in alert(session)
        assert await status_of(app_id) == "pending"

    async def test_reject_declines_request_and_informs_applicant(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await start_application(dp, bot)
        session.clear()
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, applicant_cb("reject", app_id)))
        assert await status_of(app_id) == "rejected"
        assert declined(session)[0].user_id == U
        assert session.texts_to(U) == [texts.APPLICATION_REJECTED]
        assert not session.sent_to(tf.GROUP_ID)
        # rad etilgach qabul qilib bo'lmaydi
        await admin_accept(dp, bot, app_id, admin=tf.ADMIN2_ID)
        assert await status_of(app_id) == "rejected" and not session.sent_to(tf.GROUP_ID)

    async def test_unknown_application(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        for action in ("accept", "reject"):
            await feed(dp, bot, tf.callback(tf.ADMIN_ID, applicant_cb(action, 9999)))
            assert "topilmadi" in alert(session)

    async def test_late_clicks_after_accept_are_refused(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id)
        session.clear()
        await admin_accept(dp, bot, app_id, admin=tf.ADMIN2_ID)
        assert "allaqachon" in alert(session)
        assert not session.sent_to(tf.GROUP_ID)  # ikkinchi ovoz xabari yuborilmaydi
        await feed(dp, bot, tf.callback(tf.ADMIN2_ID, applicant_cb("reject", app_id)))
        assert await status_of(app_id) == "voting" and not declined(session)

    async def test_two_admins_click_simultaneously_only_one_vote_message(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await start_application(dp, bot)
        session.clear()
        await asyncio.gather(admin_accept(dp, bot, app_id, tf.ADMIN_ID), admin_accept(dp, bot, app_id, tf.ADMIN2_ID))
        assert len(session.sent_to(tf.GROUP_ID)) == 1

    @pytest.mark.parametrize(
        "make_error, alert_part",
        [(lambda m: tf.bad_request("Bad Request: not enough rights", m), "yuborib bo'lmadi"), (tf.network_error, None)],
        ids=["bad_request", "network_error"],
    )
    async def test_group_send_failure_keeps_pending_for_retry(self, dp: Dispatcher, bot: Bot, session: FakeSession, make_error: Callable, alert_part: str | None ) -> None:
        app_id = await start_application(dp, bot)
        session.errors[SendMessage] = lambda m: make_error(m) if m.chat_id == tf.GROUP_ID else None
        await admin_accept(dp, bot, app_id)
        # ariza ovoz xabarisiz "voting"da qolib ketmasligi kerak
        assert await status_of(app_id) == "pending"
        if alert_part:
            assert alert_part in alert(session)
        session.errors.clear()
        await admin_accept(dp, bot, app_id)
        assert await status_of(app_id) == "voting"


class TestVoting:
    async def test_member_votes_yes(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        assert "Ovozingiz qabul qilindi" in alert(session) and "Ha" in alert(session)
        assert await dbm.count_votes(app_id) == (1, 0)
        assert not session.sent_to(M[0])  # 👍 sabab so'ralmaydi
        assert_no_errors(session)

    async def test_vote_cannot_be_changed_or_repeated(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await cast(dp, bot, M[0], "no", app_id)
        assert "allaqachon" in alert(session) and "Ha" in alert(session)
        for _ in range(2):
            await cast(dp, bot, M[0], "yes", app_id)
        assert await dbm.count_votes(app_id) == (1, 0)

    @pytest.mark.parametrize(
        "voter, status, alert_part",
        [(U, None, "o'z arizangizga"), (300, "left", "faqat guruh a'zolari"), (300, "kicked", None)],
        ids=["applicant", "left", "kicked"],
    )
    async def test_ineligible_voter_is_refused(self, dp: Dispatcher, bot: Bot, session: FakeSession, voter: int, status: str | None, alert_part: str | None ) -> None:
        app_id = await voting_app(dp, bot)
        if status:
            session.statuses[(tf.GROUP_ID, voter)] = status
        await cast(dp, bot, voter, "yes", app_id)
        if alert_part:
            assert alert_part in alert(session)
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_member_statuses_that_may_vote(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        statuses = {300: "restricted", 301: "restricted_out", 302: "administrator", 303: "creator"}
        for uid, status in statuses.items():
            session.statuses[(tf.GROUP_ID, uid)] = status
            await cast(dp, bot, uid, "yes", app_id)
        assert await dbm.get_vote(app_id, 301) is None  # a'zo bo'lmagan cheklangan foydalanuvchi
        assert await dbm.count_votes(app_id) == (3, 0)

    async def test_invalid_value_or_pending_application_is_ignored(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "banana", app_id)
        pending = await start_application(dp, bot, user_id=2)
        await cast(dp, bot, M[0], "yes", pending)
        assert await dbm.count_votes(app_id) == (0, 0) and await dbm.count_votes(pending) == (0, 0)

    async def test_vote_after_deadline_and_after_finalize_is_refused(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await expire_voting(app_id)
        await cast(dp, bot, M[1], "no", app_id)
        assert "muddati tugadi" in alert(session)
        await finalize_due_votings(bot)
        await cast(dp, bot, M[2], "no", app_id)
        assert "yakunlangan" in alert(session)
        assert await dbm.count_votes(app_id) == (1, 0)

    async def test_stale_vote_message_of_unknown_application_is_deleted(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        # baza tozalangan/ariza yo'q: eski ovoz xabari guruhda qolib ketmasin
        await cast(dp, bot, M[0], "yes", 999, message_id=4242)
        assert "yakunlangan" in alert(session)
        assert [m.message_id for m in session.of(DeleteMessage)] == [4242]

    async def test_vote_from_wrong_or_finished_message_is_refused_and_message_deleted(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        # app id takrorlangan bo'lishi mumkin: ovoz faqat arizaning o'z xabaridan qabul qilinadi
        app_id = await voting_app(dp, bot)
        real = (await get_app(app_id))["vote_message_id"]
        await cast(dp, bot, M[0], "yes", app_id, message_id=real + 1000)
        assert "yakunlangan" in alert(session) and await dbm.count_votes(app_id) == (0, 0)
        assert [m.message_id for m in session.of(DeleteMessage)] == [real + 1000]
        session.clear()
        await dbm.change_status(app_id, "voting", "rejected")  # tugagan arizaning xabari bosilganda o'chadi
        await cast(dp, bot, M[0], "yes", app_id)
        assert [m.message_id for m in session.of(DeleteMessage)] == [real]

    async def test_no_vote_asks_reason_by_dm(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await set_full_name(app_id, "<b>X</b> Y")
        await cast(dp, bot, M[0], "no", app_id)
        dm = session.sent_to(M[0])
        assert len(dm) == 1 and "sababini" in dm[0].text and "&lt;b&gt;X" in dm[0].text  # ism escape qilinadi
        assert dm[0].reply_markup is None  # oddiy a'zoda "o'tkazib yuborish" yo'q
        # admin ovozi ham 1 ta, lekin skip tugmasi bor
        await cast(dp, bot, tf.ADMIN_ID, "no", app_id)
        assert await dbm.count_votes(app_id) == (0, 2)
        assert reply_buttons(session.sent_to(tf.ADMIN_ID)[0]) == [texts.SKIP_BUTTON]

    async def test_reason_dm_failure_tells_voter_to_press_start(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        session.errors[SendMessage] = lambda m: (
            tf.bad_request("Forbidden: bot can't initiate conversation", m) if m.chat_id == M[0] else None
        )
        await cast(dp, bot, M[0], "no", app_id)
        assert "/start" in alert(session)
        assert await dbm.count_votes(app_id) == (0, 1)  # ovoz baribir qabul qilingan

    async def test_concurrent_votes_from_many_members_are_all_counted(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await asyncio.gather(*(cast(dp, bot, uid, "yes", app_id) for uid in range(300, 320)))
        assert await dbm.count_votes(app_id) == (20, 0)


class TestResultsEndToEnd:
    async def test_accepted_by_vote(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        for uid in M[:3]:
            await cast(dp, bot, uid, "yes", app_id)
        for uid in M[3:5]:
            await cast(dp, bot, uid, "no", app_id)
        await close_vote(bot, app_id, session)
        assert await status_of(app_id) == "accepted"
        assert session.of(ApproveChatJoinRequest)[0].user_id == U
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED]
        assert session.of(DeleteMessage)

    async def test_rejected_by_vote_with_soft_feedback_only(self, dp: Dispatcher, bot: Bot, session: FakeSession, summary_ai: Callable) -> None:
        summary_ai("Anketani batafsilroq yozing.")
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        for uid in M[1:4]:
            await cast(dp, bot, uid, "no", app_id)
            await feed(dp, bot, tf.private_message(uid, "Ismi g'alati"))
        await close_vote(bot, app_id, session)
        assert await status_of(app_id) == "rejected"
        note = session.texts_to(U)[0]
        assert note.startswith(texts.APPLICATION_REJECTED) and "batafsilroq" in note and "g'alati" not in note
        assert declined(session)

    async def test_no_votes_expires_and_user_can_reapply(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        await close_vote(bot, app_id, session)
        assert await status_of(app_id) == "expired"
        assert "hech kim ovoz bermadi" in session.texts_to(U)[0]
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U)[0] != texts.ALREADY_APPLIED
