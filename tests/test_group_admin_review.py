"""Anketa, ovoz va qaror: guruhning Telegram adminlari (ADMIN_IDS dan tashqari ham) ishlay oladi; guruh buyruqlari esa faqat ADMIN_IDS."""
import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import BanChatMember, GetChatAdministrators, SendMessage
from aiogram.types import ReplyKeyboardMarkup

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.flow import (
    admin_accept,
    applicant_cb,
    cast,
    decision_cb,
    feed,
    last_alert,
    start_application,
    status_of,
)
from tests.telegram_fakes import FakeSession
from tests.test_flow_voting import M, U, close_vote, inline, voting_app
from utils.admin import reviewer_ids
from utils.applications import redeliver_undelivered

G = tf.GROUP_ID
GA = 5001  # guruh admini, ADMIN_IDS da yo'q
OWNER = 5002  # guruh egasi
STRANGER = 555


@pytest.fixture
def group_admins(session: FakeSession) -> None:
    session.group_admins[G] = [GA]
    session.statuses[(G, OWNER)] = "creator"


class TestRecipients:
    async def test_reviewer_ids_are_group_admins_and_env_admins_without_bots(self, bot: Bot, session: FakeSession, group_admins: None) -> None:
        ids = await reviewer_ids(bot, G)
        assert set(ids) == {GA, OWNER, tf.ADMIN_ID, tf.ADMIN2_ID}
        assert tf.BOT_ID not in ids

    async def test_group_admins_unavailable_falls_back_to_env_admins(self, bot: Bot, session: FakeSession, group_admins: None) -> None:
        session.errors[GetChatAdministrators] = lambda m: tf.forbidden(m)
        assert set(await reviewer_ids(bot, G)) == {tf.ADMIN_ID, tf.ADMIN2_ID}

    async def test_anketa_goes_to_every_group_admin(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await start_application(dp, bot)
        for admin in (GA, OWNER, tf.ADMIN_ID, tf.ADMIN2_ID):
            msgs = [m for m in session.sent_to(admin) if "Aziz Karimov" in (m.text or "")]
            assert len(msgs) == 1 and inline(msgs[0]) == [f"app:accept:{app_id}", f"app:reject:{app_id}"]
        assert not session.sent_to(tf.BOT_ID) and not session.sent_to(STRANGER)

    async def test_undelivered_application_is_redelivered_to_group_admins(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await start_application(dp, bot)
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET admins_notified = 0 WHERE id = ?", (app_id,))
        await d.commit()
        session.clear()
        assert await redeliver_undelivered(bot, dp.storage) == 1
        assert {GA, OWNER} <= {m.chat_id for m in session.of(SendMessage)}


class TestAnketaReview:
    async def test_group_admin_can_put_to_vote(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id, admin=GA)
        assert await status_of(app_id) == "voting"

    async def test_group_owner_can_reject(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await start_application(dp, bot)
        await feed(dp, bot, tf.callback(OWNER, applicant_cb("reject", app_id)))
        assert await status_of(app_id) == "rejected"

    async def test_env_admin_who_is_not_group_admin_still_can(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id, admin=tf.ADMIN2_ID)
        assert await status_of(app_id) == "voting"

    @pytest.mark.parametrize("action", ["accept", "reject"])
    async def test_regular_member_is_refused(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None, action: str) -> None:
        app_id = await start_application(dp, bot)
        await feed(dp, bot, tf.callback(STRANGER, applicant_cb(action, app_id)))
        assert await status_of(app_id) == "pending" and "faqat adminlar" in (last_alert(session).text or "")

    async def test_admin_of_another_group_cannot_review(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        other = -1009999
        session.group_admins[G] = [GA]  # GA faqat G ning admini
        app_id = await start_application(dp, bot, group_id=other)
        await feed(dp, bot, tf.callback(GA, applicant_cb("accept", app_id)))
        assert await status_of(app_id) == "pending"


class TestVotingAndDecision:
    async def _tie(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> int:
        app_id = await voting_app(dp, bot)
        for uid in M[:2]:
            await cast(dp, bot, uid, "yes", app_id)
        for uid in M[2:4]:
            await cast(dp, bot, uid, "no", app_id)
        await close_vote(bot, app_id, session)
        assert await status_of(app_id) == "admin_decision"
        return app_id

    async def test_tie_report_reaches_group_admins_and_one_of_them_decides(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await self._tie(dp, bot, session)
        for admin in (GA, OWNER):
            assert any(f"decision:accept:{app_id}" in inline(m) for m in session.sent_to(admin) if m.reply_markup)
        session.clear()
        await feed(dp, bot, tf.callback(GA, decision_cb("final_accept", app_id)))
        assert await status_of(app_id) == "accepted"
        # qolgan guruh adminlari natija statusini oladi, qaror qilganning o'ziga yuborilmaydi
        assert any("qabul qilindi" in t for t in session.texts_to(OWNER))
        assert not any("qaror:" in t for t in session.texts_to(GA))

    async def test_regular_member_cannot_decide(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await self._tie(dp, bot, session)
        await feed(dp, bot, tf.callback(STRANGER, decision_cb("final_accept", app_id)))
        assert await status_of(app_id) == "admin_decision"

    async def test_final_status_goes_to_group_admins(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await voting_app(dp, bot)
        for uid in M[:3]:
            await cast(dp, bot, uid, "yes", app_id)
        await close_vote(bot, app_id, session)
        for admin in (GA, OWNER):
            assert any("guruhga qabul qilindi" in t for t in session.texts_to(admin))

    async def test_group_admin_voting_no_gets_reason_dm_with_skip_button(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, GA, "no", app_id)
        dm = session.sent_to(GA)[0]
        assert isinstance(dm.reply_markup, ReplyKeyboardMarkup)
        session.clear()
        await feed(dp, bot, tf.private_message(GA, texts.SKIP_BUTTON))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] == ""

    async def test_regular_member_has_no_skip_button_and_cannot_skip(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None) -> None:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, STRANGER, "no", app_id)
        assert session.sent_to(STRANGER)[0].reply_markup is None
        await feed(dp, bot, tf.private_message(STRANGER, texts.SKIP_BUTTON))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] != ""


class TestCommandsStayEnvOnly:
    @pytest.mark.parametrize("user", [GA, OWNER])
    async def test_group_admin_cannot_run_bot_commands(self, dp: Dispatcher, bot: Bot, session: FakeSession, group_admins: None, user: int) -> None:
        victim = tf.group_message_obj(777, "spam", message_id=4321)
        await feed(dp, bot, tf.group_message(user, "/ban", reply_to=victim))
        assert not session.of(BanChatMember)
