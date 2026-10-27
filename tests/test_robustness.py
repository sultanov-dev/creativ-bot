"""Chekka holatlar: atomik ovoz, so'rov bajarilmasa, bot to'xtagandan keyin tiklash, chiqarilgan foydalanuvchi."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import ApproveChatJoinRequest, SendMessage
from aiogram.types import Chat, ChatMemberBanned, ChatMemberMember, ChatMemberUpdated, Update

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.flow import admin_accept, cast, feed, start_application, status_of
from utils.join_requests import recover_unresolved
from utils.voting import finalize_due_votings

U = 1
G = tf.GROUP_ID
M = [200, 201, 202, 203, 204]


async def accepted_by_vote(dp, bot, user=U):
    app_id = await start_application(dp, bot, user_id=user)
    await admin_accept(dp, bot, app_id)
    for uid in M[:3]:
        await cast(dp, bot, uid, "yes", app_id)
    await expire_voting(app_id)
    bot.session.clear()
    await finalize_due_votings(bot)
    return app_id


async def join_resolved(app_id):
    return (await dbm.get_application(app_id))["join_resolved"]


class TestAtomicVote:
    async def _app(self, db):
        a = await dbm.create_application(1, G, "Aziz Karimov", "anketa\n")
        return a

    async def test_vote_refused_while_pending(self, db):
        a = await self._app(db)
        assert await dbm.add_vote(a, 10, "yes") is False
        assert await dbm.count_votes(a) == (0, 0)

    async def test_vote_refused_after_deadline_even_if_status_still_voting(self, db):
        a = await self._app(db)
        await dbm.start_voting(a, 10)
        await expire_voting(a)
        assert await dbm.add_vote(a, 10, "yes") is False
        assert await dbm.count_votes(a) == (0, 0)

    async def test_vote_refused_after_final_status(self, db):
        a = await self._app(db)
        await dbm.start_voting(a, 10)
        await dbm.change_status(a, "voting", "rejected")
        assert await dbm.add_vote(a, 10, "yes") is False

    async def test_vote_accepted_while_open(self, db):
        a = await self._app(db)
        await dbm.start_voting(a, 10)
        assert await dbm.add_vote(a, 10, "yes") is True


class TestJoinRequestResult:
    async def test_normal_accept_marks_resolved(self, dp, bot, session):
        app_id = await accepted_by_vote(dp, bot)
        assert await status_of(app_id) == "accepted" and await join_resolved(app_id) == 1
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED]

    async def test_approve_fails_and_user_not_in_group(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id)
        for uid in M[:3]:
            await cast(dp, bot, uid, "yes", app_id)
        await expire_voting(app_id)
        session.clear()
        session.errors[ApproveChatJoinRequest] = lambda m: TelegramBadRequest(method=m, message="HIDE_REQUESTER_MISSING")
        session.statuses[(G, U)] = "left"
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted" and await join_resolved(app_id) == 1
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED_NOT_JOINED]
        admin_texts = session.texts_to(tf.ADMIN_ID)
        assert len(admin_texts) == 1 and "qo'shib bo'lmadi" in admin_texts[0]
        assert "guruhga qabul qilindi" not in admin_texts[0]

    async def test_approve_error_but_already_member_is_fine(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id)
        for uid in M[:3]:
            await cast(dp, bot, uid, "yes", app_id)
        await expire_voting(app_id)
        session.clear()
        session.errors[ApproveChatJoinRequest] = lambda m: TelegramBadRequest(method=m, message="USER_ALREADY_PARTICIPANT")
        session.statuses[(G, U)] = "member"
        await finalize_due_votings(bot)
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED]
        assert "guruhga qabul qilindi" in session.texts_to(tf.ADMIN_ID)[0]

    async def test_admin_decision_with_failed_approve_warns(self, dp, bot, session):
        from tests.flow import creator_cb

        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id)
        for uid in M[:2]:
            await cast(dp, bot, uid, "yes", app_id)
        for uid in M[2:4]:
            await cast(dp, bot, uid, "no", app_id)
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "creator_review"
        session.clear()
        session.errors[ApproveChatJoinRequest] = lambda m: TelegramBadRequest(method=m, message="gone")
        session.statuses[(G, U)] = "left"
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("final_accept", app_id)))
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED_NOT_JOINED]
        assert any("qo'shib bo'lmadi" in t for t in session.texts_to(tf.ADMIN2_ID))


class TestRecoveryAfterCrash:
    async def test_final_status_sets_unresolved_until_settled(self, db):
        a = await dbm.create_application(1, G, "Aziz Karimov", "anketa\n")
        await dbm.change_status(a, "pending", "rejected")
        assert (await dbm.get_application(a))["join_resolved"] == 0
        assert [x["id"] for x in await dbm.get_unresolved_join_requests()] == [a]
        await dbm.mark_join_resolved(a)
        assert await dbm.get_unresolved_join_requests() == []

    async def test_non_final_status_does_not_unresolve(self, db):
        a = await dbm.create_application(1, G, "Aziz Karimov", "anketa\n")
        await dbm.change_status(a, "pending", "voting")
        assert (await dbm.get_application(a))["join_resolved"] == 1

    async def test_recover_approves_interrupted_accept(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "accepted")  # bot shu yerda to'xtadi
        session.clear()
        assert await recover_unresolved(bot) == 1
        assert [(m.chat_id, m.user_id) for m in session.of(ApproveChatJoinRequest)] == [(G, U)]
        assert await join_resolved(app_id) == 1
        assert await recover_unresolved(bot) == 0

    async def test_recover_declines_interrupted_reject(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "rejected")
        session.clear()
        await recover_unresolved(bot)
        assert not session.of(ApproveChatJoinRequest) and await join_resolved(app_id) == 1

    async def test_old_rows_are_not_retried(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "accepted")
        await dbm.mark_join_resolved(app_id)
        session.clear()
        assert await recover_unresolved(bot) == 0 and not session.requests


class TestRemovedUserNeedsReview:
    async def _joined_user(self, dp, bot):
        app_id = await accepted_by_vote(dp, bot)
        assert await status_of(app_id) == "accepted"
        return app_id

    async def test_ban_command_marks_removed(self, dp, bot, session):
        app_id = await self._joined_user(dp, bot)
        await feed(dp, bot, tf.group_message(tf.ADMIN_ID, "/ban", reply_to=tf.group_message_obj(U, "x")))
        assert await status_of(app_id) == "removed"

    async def test_kick_command_marks_removed(self, dp, bot, session):
        app_id = await self._joined_user(dp, bot)
        assert await dbm.mark_removed(U, G) == 1
        assert await status_of(app_id) == "removed"

    async def test_manual_telegram_ban_marks_removed(self, dp, bot, session):
        app_id = await self._joined_user(dp, bot)
        user = tf.make_user(U, "U1")
        event = ChatMemberUpdated(
            chat=Chat(id=G, type="supergroup", title="G"), from_user=tf.make_user(tf.ADMIN_ID, "A"), date=tf.now(),
            old_chat_member=ChatMemberMember(status="member", user=user),
            new_chat_member=ChatMemberBanned(status="kicked", user=user, until_date=tf.now()),
        )
        await feed(dp, bot, Update(update_id=991, chat_member=event))
        assert await status_of(app_id) == "removed"

    async def test_rejoin_after_removal_starts_fresh_questionnaire(self, dp, bot, session):
        app_id = await self._joined_user(dp, bot)
        await dbm.mark_removed(U, G)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert sent[0] == texts.REJOIN_AFTER_REMOVED and sent[1] == texts.ASK_FULL_NAME
        # saqlangan anketa ko'rsatilmadi va ovozga to'g'ridan-to'g'ri ketmadi
        assert await dbm.get_active_application(U, G) is None

    async def test_removal_does_not_touch_other_users_or_other_statuses(self, db):
        a = await dbm.create_application(1, G, "A B", "x\n")
        await dbm.change_status(a, "pending", "rejected")
        assert await dbm.mark_removed(1, G) == 0
        assert await dbm.mark_removed(2, G) == 0
