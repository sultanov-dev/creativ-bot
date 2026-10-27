"""Qayta ariza kutishi, ovoz xabari muddati, yetim ovoz xabari, eski ma'lumotlarni o'chirish, status nomi migratsiyasi."""
import pytest
from aiogram.methods import DeclineChatJoinRequest, DeleteMessage

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.flow import admin_accept, feed, start_application, status_of
from utils.timefmt import format_deadline, format_wait

G = tf.GROUP_ID
U = 1


async def age_decision(app_id, interval="-3 minutes"):
    d = await dbm.get_db()
    await d.execute("UPDATE applications SET decided_at = datetime('now', ?) WHERE id = ?", (interval, app_id))
    await d.commit()


class TestFormatting:
    @pytest.mark.parametrize("seconds,text", [(45, "45 soniya"), (60, "1 daqiqa"), (80, "1 daqiqa 20 soniya"), (0, "1 soniya")])
    def test_wait(self, seconds, text):
        assert format_wait(seconds) == text

    @pytest.mark.parametrize("minutes,text", [(10, "10 daqiqada"), (90, "90 daqiqada"), (120, "2 soatda"), (2880, "2 kunda")])
    def test_deadline(self, minutes, text):
        assert format_deadline(minutes) == text


class TestCooldown:
    @pytest.fixture(autouse=True)
    def cooldown(self, monkeypatch):
        import handlers.join

        monkeypatch.setattr(handlers.join, "REJOIN_COOLDOWN_SECONDS", 120)

    @pytest.mark.parametrize("status", ["rejected", "expired", "failed"])
    async def test_rejoin_inside_cooldown_is_refused_with_time(self, dp, bot, session, status):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", status)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert len(sent) == 1 and "kuting" in sent[0] and ("daqiqa" in sent[0] or "soniya" in sent[0])
        assert [(m.chat_id, m.user_id) for m in session.of(DeclineChatJoinRequest)] == [(G, U)]
        assert texts.ASK_FULL_NAME not in sent

    async def test_after_cooldown_questionnaire_starts(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "rejected")
        await age_decision(app_id, "-3 minutes")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.REJOIN_AFTER_REJECTION, texts.ASK_FULL_NAME]
        assert not session.of(DeclineChatJoinRequest)

    async def test_no_cooldown_for_new_user_or_accepted(self, db):
        assert await dbm.rejoin_wait_seconds(5, G, 120) == 0
        a = await dbm.create_application(U, G, "A B", "x\n")
        await dbm.change_status(a, "pending", "accepted")
        assert await dbm.rejoin_wait_seconds(U, G, 120) == 0

    async def test_zero_disables(self, db):
        a = await dbm.create_application(U, G, "A B", "x\n")
        await dbm.change_status(a, "pending", "rejected")
        assert await dbm.rejoin_wait_seconds(U, G, 0) == 0
        assert 0 < await dbm.rejoin_wait_seconds(U, G, 120) <= 120


class TestVoteMessage:
    async def test_deadline_line_from_config(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        session.clear()
        await admin_accept(dp, bot, app_id)
        text = session.sent_to(G)[0].text
        assert "⏳ Ovoz berish 10 daqiqada tugaydi." in text


class TestOrphanVoteMessage:
    async def test_voting_without_message_goes_back_to_pending(self, db):
        a = await dbm.create_application(U, G, "A B", "x\n")
        await dbm.start_voting(a, 10)
        assert await dbm.reset_orphan_votings() == 1
        app = await dbm.get_application(a)
        assert app["status"] == "pending" and app["voting_ends_at"] is None

    async def test_voting_with_message_is_kept(self, db):
        a = await dbm.create_application(U, G, "A B", "x\n")
        await dbm.start_voting(a, 10)
        await dbm.set_vote_message(a, 55)
        assert await dbm.reset_orphan_votings() == 0 and (await dbm.get_application(a))["status"] == "voting"

    async def test_failed_message_id_write_deletes_message_and_reverts(self, dp, bot, session, monkeypatch):
        import utils.applications as apps

        app_id = await start_application(dp, bot)

        async def boom(**kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(apps, "set_vote_message", boom)
        session.clear()
        assert await apps.open_voting(bot, await dbm.get_application(app_id)) is False
        assert await status_of(app_id) == "pending" and session.of(DeleteMessage)


class TestRetention:
    async def _old(self, user, status, interval="-40 days", group=G):
        a = await dbm.create_application(user, group, "A B", "anketa\n", phone="+998901234567")
        await dbm.save_profile(user, {"phone": "+998901234567"})
        await dbm.change_status(a, "pending", status) if status != "pending" else None
        await age_decision(a, interval)
        return a

    @pytest.mark.parametrize("status", ["rejected", "expired", "failed"])
    async def test_old_data_is_deleted_with_votes_and_profile(self, db, status):
        a = await self._old(U, status)
        d = await dbm.get_db()
        await d.execute("INSERT INTO votes (application_id, voter_id, vote, reason) VALUES (?, 9, 'no', 'sabab')", (a,))
        await d.commit()
        assert await dbm.purge_old_data(30) == 1
        assert await dbm.get_application(a) is None
        assert await dbm.get_profile(U) is None
        assert (await (await d.execute("SELECT COUNT(*) FROM votes")).fetchone())[0] == 0

    async def test_removed_is_purged_too(self, db):
        a = await dbm.create_application(U, G, "A B", "x\n")
        await dbm.save_profile(U, {"phone": "1"})
        await dbm.change_status(a, "pending", "accepted")
        await dbm.mark_removed(U, G)
        await age_decision(a, "-40 days")
        assert await dbm.purge_old_data(30) == 1 and await dbm.get_profile(U) is None

    async def test_recent_is_kept(self, db):
        a = await self._old(U, "rejected", "-5 days")
        assert await dbm.purge_old_data(30) == 0
        assert await dbm.get_application(a) is not None and await dbm.get_profile(U) is not None

    async def test_accepted_member_is_never_purged(self, db):
        a = await self._old(U, "accepted", "-400 days")
        assert await dbm.purge_old_data(30) == 0 and await dbm.get_application(a) is not None

    async def test_profile_stays_if_user_has_other_application(self, db):
        await self._old(U, "rejected")
        fresh = await dbm.create_application(U, G, "A B", "again\n")
        assert await dbm.purge_old_data(30) == 1
        assert await dbm.get_application(fresh) is not None and await dbm.get_profile(U) is not None

    async def test_zero_days_disables(self, db):
        a = await self._old(U, "rejected", "-4000 days")
        assert await dbm.purge_old_data(0) == 0 and await dbm.get_application(a) is not None

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
        a = await dbm.create_application(U, G, "A B", "x\n")
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET status = 'creator_review' WHERE id = ?", (a,))
        await d.commit()
        await dbm.init_db()
        assert (await dbm.get_application(a))["status"] == "admin_decision"
        # indeks yangilandi: shu foydalanuvchiga ikkinchi faol ariza ochilmaydi
        assert await dbm.create_application(U, G, "A B", "y\n") is None


class TestUnfinishedQuestionnaire:
    async def test_second_join_mid_form_asks_to_finish_and_repeats_question(self, dp, bot, session):
        await feed(dp, bot, tf.join_request(U))
        await feed(dp, bot, tf.private_message(U, "Aziz Karimov"))
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert sent == [texts.FINISH_FORM_FIRST, texts.ASK_PHONE]
        # holat va javoblar saqlanib qoldi: davom ettirish mumkin
        await feed(dp, bot, tf.private_message(U, texts.SKIP_BUTTON))
        assert session.texts_to(U)[-1] == texts.ASK_AGE

    async def test_bug_case_after_expired_application_no_stale_note(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "expired")
        await feed(dp, bot, tf.join_request(U))  # eslatma + savol boshlandi
        await feed(dp, bot, tf.private_message(U, "Aziz Karimov"))
        session.clear()
        await feed(dp, bot, tf.join_request(U))  # yana so'rov: eski "muddati o'tgan" xabari emas
        sent = session.texts_to(U)
        assert texts.REJOIN_AFTER_EXPIRED not in sent
        assert sent[0] == texts.FINISH_FORM_FIRST

    async def test_first_question_is_repeated_too(self, dp, bot, session):
        await feed(dp, bot, tf.join_request(U))
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.FINISH_FORM_FIRST, texts.ASK_FULL_NAME]

    async def test_other_group_still_starts_fresh(self, dp, bot, session):
        await feed(dp, bot, tf.join_request(U))
        await feed(dp, bot, tf.private_message(U, "Aziz Karimov"))
        session.clear()
        await feed(dp, bot, tf.join_request(U, chat_id=-1009999))
        assert texts.FINISH_FORM_FIRST not in session.texts_to(U)
        assert session.texts_to(U)[-1] == texts.ASK_FULL_NAME

    async def test_after_completed_application_state_is_clear(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "rejected")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert texts.FINISH_FORM_FIRST not in session.texts_to(U)


class TestBotStoppedMidFlow:
    async def test_welcome_cannot_be_sent_state_cleared_and_request_declined(self, dp, bot, session):
        from aiogram.exceptions import TelegramForbiddenError
        from aiogram.methods import SendMessage

        session.errors[SendMessage] = lambda m: (
            TelegramForbiddenError(method=m, message="Forbidden: bot can't initiate conversation")
            if m.chat_id == U else None
        )
        await feed(dp, bot, tf.join_request(U))
        ctx = dp.fsm.get_context(bot, chat_id=U, user_id=U)
        assert await ctx.get_state() is None
        assert [(m.chat_id, m.user_id) for m in session.of(DeclineChatJoinRequest)] == [(G, U)]
        assert not session.sent_to(tf.DEVELOPER_ID)  # dasturchiga xato ketmadi

    async def test_crash_after_application_created_keeps_answers_and_retry_reaches_admins(
        self, dp, bot, session, monkeypatch
    ):
        import handlers.anketa as anketa

        await feed(dp, bot, tf.join_request(U))
        for a in ANSWERS_BEFORE_LAST:
            await feed(dp, bot, tf.private_message(U, a))

        real_send = anketa.safe_send

        async def crashing(**kw):
            raise RuntimeError("bot to'xtadi")

        monkeypatch.setattr(anketa, "safe_send", crashing)
        await feed(dp, bot, tf.private_message(U, "Qiziq"))
        ctx = dp.fsm.get_context(bot, chat_id=U, user_id=U)
        assert await ctx.get_state() == "Form:join_group"  # javoblar yo'qolmadi
        pending = await dbm.get_active_application(U, G)
        assert pending is not None and pending["status"] == "pending"
        assert not session.sent_to(tf.ADMIN_ID)

        monkeypatch.setattr(anketa, "safe_send", real_send)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "Qiziq"))  # oxirgi javob qayta ishlanadi (redelivery)
        assert len(session.sent_to(tf.ADMIN_ID)) == 1 and len(session.sent_to(tf.ADMIN2_ID)) == 1
        assert await ctx.get_state() is None
        assert texts.THANKS in session.texts_to(U)
        d = await dbm.get_db()
        assert (await (await d.execute("SELECT COUNT(*) FROM applications")).fetchone())[0] == 1  # dublikat yo'q

    async def test_state_is_cleared_only_after_admins_got_it(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        ctx = dp.fsm.get_context(bot, chat_id=U, user_id=U)
        assert await ctx.get_state() is None and app_id
        assert len(session.sent_to(tf.ADMIN_ID)) == 1

    async def test_double_tap_on_last_answer_makes_one_application(self, dp, bot, session):
        import asyncio

        await feed(dp, bot, tf.join_request(U))
        for a in ANSWERS_BEFORE_LAST:
            await feed(dp, bot, tf.private_message(U, a))
        session.clear()
        await asyncio.gather(
            feed(dp, bot, tf.private_message(U, "Qiziq")), feed(dp, bot, tf.private_message(U, "Qiziq"))
        )
        assert len(session.sent_to(tf.ADMIN_ID)) == 1
        d = await dbm.get_db()
        assert (await (await d.execute("SELECT COUNT(*) FROM applications")).fetchone())[0] == 1

    async def test_no_admin_reachable_marks_failed_and_clears_state(self, dp, bot, session):
        from aiogram.exceptions import TelegramForbiddenError
        from aiogram.methods import SendMessage

        await feed(dp, bot, tf.join_request(U))
        for a in ANSWERS_BEFORE_LAST:
            await feed(dp, bot, tf.private_message(U, a))
        session.errors[SendMessage] = lambda m: (
            TelegramForbiddenError(method=m, message="Forbidden") if m.chat_id in (tf.ADMIN_ID, tf.ADMIN2_ID) else None
        )
        await feed(dp, bot, tf.private_message(U, "Qiziq"))
        assert await dbm.last_application_status(U, G) == "failed"
        assert await dp.fsm.get_context(bot, chat_id=U, user_id=U).get_state() is None
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC


ANSWERS_BEFORE_LAST = ["Aziz Karimov", texts.SKIP_BUTTON, "25", "Dasturchi", "O'zim haqimda"]
