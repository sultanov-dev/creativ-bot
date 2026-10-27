"""Admin ko'rigi -> guruh ovozi -> natija -> creator (admin) qarori: butun hayot tsikli."""
import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import ApproveChatJoinRequest, DeleteMessage, SendMessage

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.flow import (
    admin_accept,
    applicant_cb,
    assert_no_errors,
    cast,
    creator_cb,
    declined,
    edits,
    feed,
    last_alert,
    start_application,
    status_of,
)
from utils.voting import finalize_due_votings

U = 1
M = [200, 201, 202, 203, 204]  # oddiy guruh a'zolari


async def voting_app(dp, bot, user=U):
    app_id = await start_application(dp, bot, user_id=user)
    await admin_accept(dp, bot, app_id)
    bot.session.clear()
    return app_id


class TestAdminReview:
    async def test_accept_puts_application_to_group_vote(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.clear()
        await admin_accept(dp, bot, app_id)
        assert await status_of(app_id) == "voting"
        app = await dbm.get_application(app_id)
        group_msgs = session.sent_to(tf.GROUP_ID)
        assert len(group_msgs) == 1 and app["vote_message_id"] is not None
        assert "Yangi a'zo uchun ovoz berish" in group_msgs[0].text
        assert "+998" not in group_msgs[0].text and app["voting_ends_at"]
        buttons = [b.callback_data for row in group_msgs[0].reply_markup.inline_keyboard for b in row]
        assert buttons == [f"vote:yes:{app_id}", f"vote:no:{app_id}"]
        assert "ovoziga qo'yildi" in session.texts_to(U)[0]
        assert any("Ovozga qo'yildi" in e.text for e in edits(session))
        assert_no_errors(session)

    async def test_non_admin_cannot_accept_or_reject(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        for action in ("accept", "reject"):
            await feed(dp, bot, tf.callback(555, applicant_cb(action, app_id)))
            assert "faqat adminlar" in last_alert(session).text
        assert await status_of(app_id) == "pending"

    async def test_applicant_cannot_approve_own_application(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await feed(dp, bot, tf.callback(U, applicant_cb("accept", app_id)))
        assert await status_of(app_id) == "pending"

    async def test_reject_declines_request_and_informs_applicant(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.clear()
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, applicant_cb("reject", app_id)))
        assert await status_of(app_id) == "rejected"
        assert declined(session)[0].user_id == U
        assert session.texts_to(U) == [texts.APPLICATION_REJECTED]
        assert not session.sent_to(tf.GROUP_ID)

    async def test_unknown_application(self, dp, bot, session):
        for action in ("accept", "reject"):
            await feed(dp, bot, tf.callback(tf.ADMIN_ID, applicant_cb(action, 9999)))
            assert "topilmadi" in last_alert(session).text

    async def test_second_click_is_refused(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id)
        session.clear()
        await admin_accept(dp, bot, app_id, admin=tf.ADMIN2_ID)
        assert "allaqachon" in last_alert(session).text
        assert not session.sent_to(tf.GROUP_ID)  # ikkinchi ovoz xabari yuborilmaydi

    async def test_reject_after_accept_does_not_override(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await admin_accept(dp, bot, app_id)
        session.clear()
        await feed(dp, bot, tf.callback(tf.ADMIN2_ID, applicant_cb("reject", app_id)))
        assert await status_of(app_id) == "voting"
        assert not declined(session)

    async def test_accept_after_reject_does_not_override(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, applicant_cb("reject", app_id)))
        session.clear()
        await admin_accept(dp, bot, app_id, admin=tf.ADMIN2_ID)
        assert await status_of(app_id) == "rejected" and not session.sent_to(tf.GROUP_ID)

    async def test_two_admins_click_simultaneously_only_one_vote_message(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.clear()
        await asyncio.gather(
            admin_accept(dp, bot, app_id, tf.ADMIN_ID), admin_accept(dp, bot, app_id, tf.ADMIN2_ID)
        )
        assert len(session.sent_to(tf.GROUP_ID)) == 1

    async def test_group_send_failure_keeps_pending_for_retry(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.errors[SendMessage] = lambda m: (
            TelegramBadRequest(method=m, message="Bad Request: not enough rights") if m.chat_id == tf.GROUP_ID else None
        )
        await admin_accept(dp, bot, app_id)
        assert await status_of(app_id) == "pending"
        assert "yuborib bo'lmadi" in last_alert(session).text
        session.errors.clear()
        await admin_accept(dp, bot, app_id)
        assert await status_of(app_id) == "voting"

    async def test_network_error_sending_vote_message_must_not_leave_application_stuck(self, dp, bot, session):
        from aiogram.exceptions import TelegramNetworkError

        app_id = await start_application(dp, bot)
        session.errors[SendMessage] = lambda m: (
            TelegramNetworkError(method=m, message="timeout") if m.chat_id == tf.GROUP_ID else None
        )
        await admin_accept(dp, bot, app_id)
        # to'g'ri xulq: xabar yuborilmagan bo'lsa ariza "voting"da (ovoz xabarisiz) qolib ketmasligi kerak
        assert await status_of(app_id) == "pending"


class TestVoting:
    async def test_member_votes_yes(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        assert "Ovozingiz qabul qilindi" in last_alert(session).text and "Ha" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (1, 0)
        assert not session.sent_to(M[0])
        assert_no_errors(session)

    async def test_vote_buttons_expose_no_tallies(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.clear()
        await admin_accept(dp, bot, app_id)
        text = session.sent_to(tf.GROUP_ID)[0].reply_markup.inline_keyboard
        assert [b.text for row in text for b in row] == ["👍 Ha", "👎 Yo'q"]

    async def test_cannot_change_vote(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await cast(dp, bot, M[0], "no", app_id)
        assert "allaqachon" in last_alert(session).text and "Ha" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (1, 0)

    async def test_same_vote_twice_counts_once(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        for _ in range(3):
            await cast(dp, bot, M[0], "yes", app_id)
        assert await dbm.count_votes(app_id) == (1, 0)

    async def test_applicant_cannot_vote_on_own_application(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, U, "yes", app_id)
        assert "o'z arizangizga" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_non_member_cannot_vote(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        session.statuses[(tf.GROUP_ID, 300)] = "left"
        await cast(dp, bot, 300, "yes", app_id)
        assert "faqat guruh a'zolari" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_kicked_user_cannot_vote(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        session.statuses[(tf.GROUP_ID, 300)] = "kicked"
        await cast(dp, bot, 300, "yes", app_id)
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_restricted_member_can_vote_but_restricted_non_member_cannot(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        session.statuses[(tf.GROUP_ID, 300)] = "restricted"
        session.statuses[(tf.GROUP_ID, 301)] = "restricted_out"
        await cast(dp, bot, 300, "yes", app_id)
        await cast(dp, bot, 301, "yes", app_id)
        assert await dbm.get_vote(app_id, 300) == "yes" and await dbm.get_vote(app_id, 301) is None

    async def test_group_admins_and_owner_can_vote(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        session.statuses[(tf.GROUP_ID, 300)] = "administrator"
        session.statuses[(tf.GROUP_ID, 301)] = "creator"
        await cast(dp, bot, 300, "yes", app_id)
        await cast(dp, bot, 301, "no", app_id)
        assert await dbm.count_votes(app_id) == (1, 1)

    async def test_unknown_application(self, dp, bot, session):
        await cast(dp, bot, M[0], "yes", 9999)
        assert "yakunlangan" in last_alert(session).text

    async def test_invalid_vote_value_is_ignored(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "banana", app_id)
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_vote_on_pending_application_is_refused(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_vote_after_deadline_is_refused(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await expire_voting(app_id)
        await cast(dp, bot, M[0], "yes", app_id)
        assert "muddati tugadi" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (0, 0)

    async def test_vote_after_finalize_is_refused(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        await cast(dp, bot, M[1], "no", app_id)
        assert "yakunlangan" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (1, 0)

    async def test_stale_vote_message_of_unknown_application_is_deleted(self, dp, bot, session):
        # baza tozalangan/ariza yo'q: eski ovoz xabari guruhda qolib ketmasin
        await cast(dp, bot, M[0], "yes", 999, message_id=4242)
        assert "yakunlangan" in last_alert(session).text
        assert [m.message_id for m in session.of(DeleteMessage)] == [4242]

    async def test_vote_on_another_applications_old_message_is_not_counted_and_message_is_deleted(
        self, dp, bot, session
    ):
        # app id takrorlangan bo'lishi mumkin: ovoz faqat arizaning o'z xabaridan qabul qilinadi
        app_id = await voting_app(dp, bot)
        real = (await dbm.get_application(app_id))["vote_message_id"]
        await cast(dp, bot, M[0], "yes", app_id, message_id=real + 1000)
        assert "yakunlangan" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (0, 0)
        assert real + 1000 in [m.message_id for m in session.of(DeleteMessage)]

    async def test_vote_message_of_finished_application_is_deleted_on_click(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        real = (await dbm.get_application(app_id))["vote_message_id"]
        await dbm.change_status(app_id, "voting", "rejected")
        session.clear()
        await cast(dp, bot, M[0], "yes", app_id)
        assert [m.message_id for m in session.of(DeleteMessage)] == [real]

    async def test_admin_no_vote_counts_as_one_and_reason_is_asked_with_skip_button(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, tf.ADMIN_ID, "no", app_id)
        assert await dbm.count_votes(app_id) == (0, 1)
        dm = session.sent_to(tf.ADMIN_ID)
        assert len(dm) == 1 and "sababini" in dm[0].text
        buttons = [b.text for row in dm[0].reply_markup.keyboard for b in row]
        assert buttons == [texts.SKIP_BUTTON]

    async def test_member_reason_dm_has_no_skip_button(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "no", app_id)
        assert session.sent_to(M[0])[0].reply_markup is None

    async def test_member_no_vote_asks_reason_by_dm(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "no", app_id)
        dm = session.texts_to(M[0])
        assert len(dm) == 1 and "sababini" in dm[0] and "Aziz Karimov" in dm[0]

    async def test_applicant_name_in_reason_dm_is_escaped(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET full_name = '<b>X</b> Y' WHERE id = ?", (app_id,))
        await d.commit()
        await cast(dp, bot, M[0], "no", app_id)
        assert "&lt;b&gt;X" in session.texts_to(M[0])[0]

    async def test_reason_dm_failure_tells_voter_to_press_start(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        session.errors[SendMessage] = lambda m: (
            TelegramBadRequest(method=m, message="Forbidden: bot can't initiate conversation")
            if m.chat_id == M[0] else None
        )
        await cast(dp, bot, M[0], "no", app_id)
        assert "/start" in last_alert(session).text
        assert await dbm.count_votes(app_id) == (0, 1)  # ovoz baribir qabul qilingan

    async def test_yes_vote_never_asks_reason(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        assert not session.sent_to(M[0])

    async def test_concurrent_votes_from_many_members_are_all_counted(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await asyncio.gather(*(cast(dp, bot, uid, "yes", app_id) for uid in range(300, 320)))
        assert await dbm.count_votes(app_id) == (20, 0)


class TestReasonCapture:
    async def _no_vote(self, dp, bot):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "no", app_id)
        bot.session.clear()
        return app_id

    async def test_reply_is_stored_as_reason(self, dp, bot, session):
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "Anketa juda qisqa"))
        assert session.texts_to(M[0]) == ["Rahmat, fikringiz qabul qilindi 🙏"]
        assert [v["reason"] for v in await dbm.get_no_votes(app_id)] == ["Anketa juda qisqa"]

    async def test_second_message_is_not_a_second_reason(self, dp, bot, session):
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "birinchi"))
        session.clear()
        await feed(dp, bot, tf.private_message(M[0], "ikkinchi"))
        assert session.requests == []
        assert (await dbm.get_no_votes(app_id))[0]["reason"] == "birinchi"

    async def test_text_without_pending_vote_is_ignored(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(M[1], "salom"))
        assert session.requests == []

    async def test_commands_are_not_reasons(self, dp, bot, session):
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "/help"))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] is None

    async def test_admin_text_is_saved_as_reason(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, tf.ADMIN_ID, "no", app_id)
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "admin fikri"))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] == "admin fikri"

    async def test_admin_skip_button_skips_reason_and_is_not_asked_again(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, tf.ADMIN_ID, "no", app_id)
        session.clear()
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, texts.SKIP_BUTTON))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] == ""
        assert len(session.sent_to(tf.ADMIN_ID)) == 1
        session.clear()
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "/start"))
        assert not any("sababini" in t for t in session.texts_to(tf.ADMIN_ID))

    async def test_admin_start_reasks_pending_reason_with_skip_button(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, tf.ADMIN_ID, "no", app_id)
        session.clear()
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "/start"))
        reask = [m for m in session.sent_to(tf.ADMIN_ID) if "sababini" in m.text]
        assert len(reask) == 1 and reask[0].reply_markup is not None

    async def test_skip_text_from_a_regular_member_is_just_a_reason(self, dp, bot, session):
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], texts.SKIP_BUTTON))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] == texts.SKIP_BUTTON

    async def test_reason_after_voting_ended_is_not_accepted(self, dp, bot, session):
        app_id = await self._no_vote(dp, bot)
        await expire_voting(app_id)
        await feed(dp, bot, tf.private_message(M[0], "kech qoldim"))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] is None

    async def test_applicant_mid_questionnaire_text_is_not_a_reason(self, dp, bot, session):
        # M[0] ham anketa to'ldiryapti: javobi anketaga ketadi, sabab sifatida saqlanmaydi
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.join_request(M[0], tf.GROUP_ID - 7))
        await feed(dp, bot, tf.private_message(M[0], "Bobur Aliyev"))
        assert (await dbm.get_no_votes(app_id))[0]["reason"] is None

    async def test_start_reasks_pending_reason(self, dp, bot, session):
        await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "/start"))
        texts_ = session.texts_to(M[0])
        assert "Salom" in texts_[0] and "sababini" in texts_[1]

    async def test_start_does_not_reask_after_reason_given(self, dp, bot, session):
        await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "sabab"))
        session.clear()
        await feed(dp, bot, tf.private_message(M[0], "/start"))
        assert len(session.texts_to(M[0])) == 1

    async def test_html_reason_is_stored_raw_but_never_forwarded_raw(self, dp, bot, session, monkeypatch):
        import utils.summary as summary

        sent_to_ai = []

        async def fake_ai(messages):
            sent_to_ai.append(messages)
            return "Umumiy fikr"

        monkeypatch.setattr(summary, "ask_ai", fake_ai)
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "<script>alert(1)</script> SIR"))
        await cast(dp, bot, M[1], "no", app_id)
        await cast(dp, bot, M[2], "no", app_id)
        await expire_voting(app_id)
        session.clear()
        await finalize_due_votings(bot)
        applicant_msgs = session.texts_to(U)
        assert len(applicant_msgs) == 1 and "SIR" not in applicant_msgs[0] and "<script>" not in applicant_msgs[0]


class TestResultsEndToEnd:
    async def test_accepted_by_vote(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        for uid in M[:3]:
            await cast(dp, bot, uid, "yes", app_id)
        for uid in M[3:5]:
            await cast(dp, bot, uid, "no", app_id)
        await expire_voting(app_id)
        session.clear()
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted"
        assert session.of(ApproveChatJoinRequest)[0].user_id == U
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED]
        assert session.of(DeleteMessage)

    async def test_rejected_by_vote_with_soft_feedback_only(self, dp, bot, session, monkeypatch):
        import utils.summary as summary

        async def fake_ai(messages):
            return "Anketani batafsilroq yozing."

        monkeypatch.setattr(summary, "ask_ai", fake_ai)
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        for uid in M[1:4]:
            await cast(dp, bot, uid, "no", app_id)
            await feed(dp, bot, tf.private_message(uid, "Ismi g'alati"))
        await expire_voting(app_id)
        session.clear()
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "rejected"
        note = session.texts_to(U)[0]
        assert note.startswith(texts.APPLICATION_REJECTED) and "batafsilroq" in note and "g'alati" not in note
        assert declined(session)

    async def test_no_votes_expires(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "expired"
        assert "hech kim ovoz bermadi" in session.texts_to(U)[0]

    async def test_user_can_reapply_after_expiry(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U)[0] != texts.ALREADY_APPLIED


class TestCreatorDecision:
    async def _tie(self, dp, bot):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await cast(dp, bot, M[1], "no", app_id)
        await feed(dp, bot, tf.private_message(M[1], "Yoshi kichik ko'rindi"))
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        bot.session.clear()
        return app_id

    async def test_tie_is_escalated(self, dp, bot, session):
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await cast(dp, bot, M[1], "no", app_id)
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "creator_review"

    async def test_accept_shows_confirm_with_ai_summary_and_no_decision_yet(self, dp, bot, session, monkeypatch):
        import utils.summary as summary

        async def fake_ai(messages):
            return "Asosiy e'tiroz: yosh."

        monkeypatch.setattr(summary, "ask_ai", fake_ai)
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("accept", app_id)))
        assert await status_of(app_id) == "creator_review"
        confirm = edits(session)[-1]
        assert "Qabul qilishni tasdiqlang" in confirm.text and "Asosiy e'tiroz" in confirm.text
        data = [b.callback_data for row in confirm.reply_markup.inline_keyboard for b in row]
        assert data == [f"creator:final_accept:{app_id}", f"creator:back:{app_id}"]

    async def test_reject_shows_confirm_with_yes_count(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("reject", app_id)))
        confirm = edits(session)[-1]
        assert "Rad etishni tasdiqlang" in confirm.text and "<b>1</b>" in confirm.text
        assert await status_of(app_id) == "creator_review"

    async def test_back_returns_to_report(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("reject", app_id)))
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("back", app_id)))
        assert "qaror sizda" in edits(session)[-1].text

    async def test_final_accept(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN2_ID, creator_cb("final_accept", app_id)))
        assert await status_of(app_id) == "accepted"
        assert session.of(ApproveChatJoinRequest)[0].user_id == U
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED]
        assert any("Qabul qilindi" in e.text for e in edits(session))

    async def test_final_reject_sends_soft_note_and_declines(self, dp, bot, session, monkeypatch):
        import utils.summary as summary

        async def fake_ai(messages):
            return "Umumiy fikr."

        monkeypatch.setattr(summary, "ask_ai", fake_ai)
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("final_reject", app_id)))
        assert await status_of(app_id) == "rejected" and declined(session)
        note = session.texts_to(U)[0]
        assert "Umumiy fikr" in note and "Yoshi kichik" not in note

    async def test_first_admin_wins(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("final_accept", app_id)))
        session.clear()
        await feed(dp, bot, tf.callback(tf.ADMIN2_ID, creator_cb("final_reject", app_id)))
        assert "allaqachon" in last_alert(session).text
        assert await status_of(app_id) == "accepted" and not declined(session)

    async def test_simultaneous_final_decisions_apply_once(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        await asyncio.gather(
            feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("final_accept", app_id))),
            feed(dp, bot, tf.callback(tf.ADMIN2_ID, creator_cb("final_reject", app_id))),
        )
        assert len(session.texts_to(U)) == 1
        assert await status_of(app_id) in ("accepted", "rejected")

    async def test_non_admin_cannot_decide(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        for action in ("accept", "reject", "final_accept", "final_reject", "back"):
            await feed(dp, bot, tf.callback(M[0], creator_cb(action, app_id)))
            assert "faqat adminlar" in last_alert(session).text
        assert await status_of(app_id) == "creator_review"

    async def test_unknown_action_is_ignored(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("explode", app_id)))
        assert await status_of(app_id) == "creator_review"

    async def test_unknown_application(self, dp, bot, session):
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("final_accept", 9999)))
        assert "topilmadi" in last_alert(session).text

    async def test_buttons_on_application_not_in_review_are_refused(self, dp, bot, session):
        app_id = await voting_app(dp, bot)  # hali "voting"
        for action in ("accept", "final_accept", "final_reject"):
            await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb(action, app_id)))
        assert await status_of(app_id) == "voting"

    async def test_summary_survives_ai_outage(self, dp, bot, session):
        # AI sozlanmagan (API_URL .invalid): xulosa o'rniga sabablarning o'zi ko'rsatiladi
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("accept", app_id)))
        text = edits(session)[-1].text
        assert "Yoshi kichik" in text and "Qabul qilishni tasdiqlang" in text
        assert_no_errors(session)

    async def test_html_in_reason_is_escaped_in_admin_confirm(self, dp, bot, session, monkeypatch):
        import utils.summary as summary

        async def fake_ai(messages):
            return "<b>zararli</b> & <script>"

        monkeypatch.setattr(summary, "ask_ai", fake_ai)
        app_id = await self._tie(dp, bot)
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, creator_cb("accept", app_id)))
        text = edits(session)[-1].text
        assert "<script>" not in text and "&lt;script&gt;" in text

    async def test_admin_name_is_escaped_in_result(self, dp, bot, session):
        app_id = await self._tie(dp, bot)
        raw = tf.callback(tf.ADMIN_ID, creator_cb("final_accept", app_id)).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        raw["callback_query"]["from"]["first_name"] = "<i>Admin</i>"
        await dp.feed_raw_update(bot, raw)
        assert "<i>Admin</i>" not in edits(session)[-1].text
