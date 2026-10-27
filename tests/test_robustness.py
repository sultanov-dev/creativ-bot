"""Chekka holatlar: atomik ovoz, so'rov bajarilmasa, tiklash, chiqarilgan foydalanuvchi, sabab so'rash, adminlar qarori."""
import asyncio
from collections.abc import Callable

import pytest
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatMemberStatus
from aiogram.methods import ApproveChatJoinRequest
from aiogram.types import Chat, ChatMemberBanned, ChatMemberMember, ChatMemberUpdated, Update

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.flow import assert_no_errors, cast, decision_cb, declined, edits, feed, get_app, start_application, status_of
from tests.telegram_fakes import FakeSession
from tests.test_flow_voting import M, U, alert, clear_session, close_vote, edit_texts, inline, voting_app
from utils.join_requests import recover_unresolved
from utils.voting import finalize_due_votings

G = tf.GROUP_ID


async def voted_app(dp: Dispatcher, bot: Bot, yes: int = 3) -> int:
    """Ovoz berish ochiq ariza + `yes` ta 👍 ovozi, muddati o'tgan (hali yakunlanmagan)."""
    app_id = await voting_app(dp, bot)
    for uid in M[:yes]:
        await cast(dp, bot, uid, "yes", app_id)
    await expire_voting(app_id)
    return app_id


async def join_resolved(app_id: int) -> int:
    return (await get_app(app_id))["join_resolved"]


async def only_reason(app_id: int) -> str | None:
    """Yagona 👎 ovozning sababi."""
    return (await dbm.get_no_votes(app_id))[0]["reason"]


class TestAtomicVote:
    @pytest.mark.parametrize("stage, accepted", [("pending", False), ("expired", False), ("final", False), ("open", True)])
    async def test_vote_only_while_open(self, db: object, stage: str, accepted: bool) -> None:
        a = await dbm.create_application(1, G, "Aziz Karimov", "anketa\n")
        assert a is not None
        if stage != "pending":
            await dbm.start_voting(a, 10)
        if stage == "expired":  # muddat o'tgan, status hali "voting"
            await expire_voting(a)
        if stage == "final":
            await dbm.change_status(a, "voting", "rejected")
        assert await dbm.add_vote(a, 10, "yes") is accepted
        assert await dbm.count_votes(a) == (int(accepted), 0)


class TestJoinRequestResult:
    @pytest.mark.parametrize(
        "error, status, user_text, admin_has",
        [
            (None, None, texts.APPLICATION_ACCEPTED, "guruhga qabul qilindi"),
            ("HIDE_REQUESTER_MISSING", "left", texts.APPLICATION_ACCEPTED_NOT_JOINED, "qo'shib bo'lmadi"),
            ("USER_ALREADY_PARTICIPANT", "member", texts.APPLICATION_ACCEPTED, "guruhga qabul qilindi"),
        ],
        ids=["ok", "failed_not_in_group", "failed_but_already_member"],
    )
    async def test_approve_result(self, dp: Dispatcher, bot: Bot, session: FakeSession, error: str | None, status: str | None, user_text: str, admin_has: str) -> None:
        app_id = await voted_app(dp, bot)
        session.clear()
        if error:
            session.errors[ApproveChatJoinRequest] = lambda m: tf.bad_request(error, m)
            session.statuses[(G, U)] = status or "member"
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted" and await join_resolved(app_id) == 1
        assert session.texts_to(U) == [user_text]
        admin_texts = session.texts_to(tf.ADMIN_ID)
        assert len(admin_texts) == 1 and admin_has in admin_texts[0]
        assert ("guruhga qabul qilindi" in admin_texts[0]) == (user_text == texts.APPLICATION_ACCEPTED)

    async def test_admin_decision_with_failed_approve_warns(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await voting_app(dp, bot)
        for uid, vote in zip(M[:4], ("yes", "yes", "no", "no")):
            await cast(dp, bot, uid, vote, app_id)
        await close_vote(bot, app_id, session)
        assert await status_of(app_id) == "admin_decision"
        session.clear()
        session.errors[ApproveChatJoinRequest] = lambda m: tf.bad_request("gone", m)
        session.statuses[(G, U)] = "left"
        await feed(dp, bot, tf.callback(tf.ADMIN_ID, decision_cb("final_accept", app_id)))
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED_NOT_JOINED]
        assert any("qo'shib bo'lmadi" in t for t in session.texts_to(tf.ADMIN2_ID))


class TestRecoveryAfterCrash:
    async def test_final_status_is_unresolved_until_settled(self, db: object) -> None:
        a = await dbm.create_application(1, G, "Aziz Karimov", "anketa\n")
        b = await dbm.create_application(2, G, "Aziz Karimov", "anketa\n")
        assert a is not None and b is not None
        await dbm.change_status(a, "pending", "rejected")
        await dbm.change_status(b, "pending", "voting")  # oraliq holat hal qilinmagan bo'lmaydi
        assert (await get_app(a))["join_resolved"] == 0 and (await get_app(b))["join_resolved"] == 1
        assert [x["id"] for x in await dbm.get_unresolved_join_requests()] == [a]
        await dbm.mark_join_resolved(a)
        assert await dbm.get_unresolved_join_requests() == []
        # chiqarish boshqa foydalanuvchi va "accepted" bo'lmagan arizaga tegmaydi
        assert await dbm.mark_removed(1, G) == 0 and await dbm.mark_removed(2, G) == 0

    @pytest.mark.parametrize("final, approved", [("accepted", True), ("rejected", False)])
    async def test_recover_finishes_interrupted_request(self, dp: Dispatcher, bot: Bot, session: FakeSession, final: str, approved: bool ) -> None:
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", final)  # bot shu yerda to'xtadi
        session.clear()
        assert await recover_unresolved(bot) == 1
        assert [(m.chat_id, m.user_id) for m in session.of(ApproveChatJoinRequest)] == ([(G, U)] if approved else [])
        assert (len(declined(session)) == 1) != approved
        assert await join_resolved(app_id) == 1
        session.clear()
        assert await recover_unresolved(bot) == 0 and not session.requests  # hal qilinganlar qayta urinilmaydi


class TestRemovedUserNeedsReview:
    async def _joined_user(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> int:
        app_id = await voted_app(dp, bot)
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted"
        session.clear()
        return app_id

    @pytest.mark.parametrize("how", ["ban_command", "mark_removed", "manual_telegram_ban"])
    async def test_removal_marks_accepted_as_removed(self, dp: Dispatcher, bot: Bot, session: FakeSession, how: str) -> None:
        app_id = await self._joined_user(dp, bot, session)
        if how == "ban_command":
            await feed(dp, bot, tf.group_message(tf.ADMIN_ID, "/ban", reply_to=tf.group_message_obj(U, "x")))
        elif how == "mark_removed":
            assert await dbm.mark_removed(U, G) == 1
        else:
            user = tf.make_user(U, "U1")
            event = ChatMemberUpdated(
                chat=Chat(id=G, type="supergroup", title="G"), from_user=tf.make_user(tf.ADMIN_ID, "A"), date=tf.now(),
                old_chat_member=ChatMemberMember(status=ChatMemberStatus.MEMBER, user=user),
                new_chat_member=ChatMemberBanned(status=ChatMemberStatus.KICKED, user=user, until_date=tf.now()),
            )
            await feed(dp, bot, Update(update_id=991, chat_member=event))
        assert await status_of(app_id) == "removed"

    async def test_rejoin_after_removal_starts_fresh_questionnaire(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        await self._joined_user(dp, bot, session)
        await dbm.mark_removed(U, G)
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert sent[0] == texts.REJOIN_AFTER_REMOVED and sent[1] == texts.ASK_FULL_NAME
        # saqlangan anketa ko'rsatilmadi va ovozga to'g'ridan-to'g'ri ketmadi
        assert await dbm.get_active_application(U, G) is None


class TestReasonCapture:
    async def _no_vote(self, dp: Dispatcher, bot: Bot) -> int:
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "no", app_id)
        clear_session(bot)
        return app_id

    async def test_reply_is_stored_once_and_commands_are_not_reasons(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[1], "salom"))  # kutilayotgan ovozi yo'q: e'tiborsiz
        assert session.requests == []
        await feed(dp, bot, tf.private_message(M[0], "/help"))
        assert await only_reason(app_id) is None
        await feed(dp, bot, tf.private_message(M[0], "/start"))  # sabab hali kutilmoqda: qayta so'raladi
        sent = session.texts_to(M[0])
        assert "Salom" in sent[0] and "sababini" in sent[1]
        # oddiy a'zoning "o'tkazib yuborish" matni ham oddiy sabab
        await feed(dp, bot, tf.private_message(M[0], texts.SKIP_BUTTON))
        assert session.texts_to(M[0])[-1] == "Rahmat, fikringiz qabul qilindi 🙏"
        session.clear()
        for text in ("ikkinchi", "/start"):  # sabab berilgach: ikkinchi sabab ham, qayta so'rash ham yo'q
            await feed(dp, bot, tf.private_message(M[0], text))
        assert len(session.texts_to(M[0])) == 1 and await only_reason(app_id) == texts.SKIP_BUTTON

    @pytest.mark.parametrize("reply, stored, moderated", [(texts.SKIP_BUTTON, "", []), ("admin fikri", "admin fikri", ["admin fikri"])])
    async def test_admin_reason_skip_and_start_reask(self, dp: Dispatcher, bot: Bot, session: FakeSession, monkeypatch: pytest.MonkeyPatch, reply: str, stored: str, moderated: list[str]) -> None:
        seen: list[str] = []

        async def spy(text: str) -> bool:
            seen.append(text)
            return False

        monkeypatch.setattr("handlers.reason.is_abusive", spy)
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, tf.ADMIN_ID, "no", app_id)
        session.clear()
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "/start"))
        reask = [m for m in session.sent_to(tf.ADMIN_ID) if "sababini" in m.text]
        assert len(reask) == 1 and reask[0].reply_markup is not None
        session.clear()
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, reply))
        assert await only_reason(app_id) == stored and len(session.sent_to(tf.ADMIN_ID)) == 1
        assert seen == moderated  # skip tugmasi moderatsiyaga ketmaydi
        session.clear()
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "/start"))
        assert not any("sababini" in t for t in session.texts_to(tf.ADMIN_ID))  # qayta so'ralmaydi

    async def test_abusive_reason_is_refused_and_can_be_rewritten(self, dp: Dispatcher, bot: Bot, session: FakeSession, monkeypatch: pytest.MonkeyPatch ) -> None:
        async def fake(text: str) -> bool:
            return "SOKINISH" in text

        monkeypatch.setattr("handlers.reason.is_abusive", fake)
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "SOKINISH"))
        assert session.texts_to(M[0]) == [texts.MODERATION_WARNING]
        assert await only_reason(app_id) is None  # saqlanmadi, hali so'raladi
        await feed(dp, bot, tf.private_message(M[0], "anketa qisqa"))
        assert await only_reason(app_id) == "anketa qisqa"

    async def test_reason_after_voting_ended_is_not_accepted(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._no_vote(dp, bot)
        await expire_voting(app_id)
        await feed(dp, bot, tf.private_message(M[0], "kech qoldim"))
        assert await only_reason(app_id) is None

    async def test_applicant_mid_questionnaire_text_is_not_a_reason(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        # M[0] ham anketa to'ldiryapti: javobi anketaga ketadi, sabab sifatida saqlanmaydi
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.join_request(M[0], G - 7))
        await feed(dp, bot, tf.private_message(M[0], "Bobur Aliyev"))
        assert await only_reason(app_id) is None

    async def test_html_reason_is_stored_raw_but_never_forwarded_raw(self, dp: Dispatcher, bot: Bot, session: FakeSession, summary_ai: Callable ) -> None:
        summary_ai("Umumiy fikr")
        app_id = await self._no_vote(dp, bot)
        await feed(dp, bot, tf.private_message(M[0], "<script>alert(1)</script> SIR"))
        await cast(dp, bot, M[1], "no", app_id)
        await cast(dp, bot, M[2], "no", app_id)
        await close_vote(bot, app_id, session)
        applicant_msgs = session.texts_to(U)
        assert len(applicant_msgs) == 1 and "SIR" not in applicant_msgs[0] and "<script>" not in applicant_msgs[0]


class TestAdminDecision:
    async def _tie(self, dp: Dispatcher, bot: Bot) -> int:
        """1 👍 / 1 👎: ovoz natijasi adminlarga o'tadi."""
        app_id = await voting_app(dp, bot)
        await cast(dp, bot, M[0], "yes", app_id)
        await cast(dp, bot, M[1], "no", app_id)
        await feed(dp, bot, tf.private_message(M[1], "Yoshi kichik ko'rindi"))
        await expire_voting(app_id)
        await finalize_due_votings(bot)
        assert await status_of(app_id) == "admin_decision"
        clear_session(bot)
        return app_id

    async def _click(self, dp: Dispatcher, bot: Bot, action: str, app_id: int, admin: int = tf.ADMIN_ID) -> None:
        await feed(dp, bot, tf.callback(admin, decision_cb(action, app_id)))

    @pytest.mark.parametrize(
        "ai_reply, shown, hidden",
        [("Asosiy e'tiroz: yosh.", "Asosiy e'tiroz", None), ("<b>zararli</b> & <script>", "&lt;script&gt;", "<script>")],
        ids=["summary", "html_escaped"],
    )
    async def test_accept_confirm_shows_ai_summary_and_decides_nothing(self, dp: Dispatcher, bot: Bot, session: FakeSession, summary_ai: Callable, ai_reply: str, shown: str, hidden: str | None ) -> None:
        summary_ai(ai_reply)
        app_id = await self._tie(dp, bot)
        await self._click(dp, bot, "accept", app_id)
        assert await status_of(app_id) == "admin_decision"
        text = edit_texts(session)[-1]
        assert "Qabul qilishni tasdiqlang" in text and shown in text and (hidden is None or hidden not in text)
        assert inline(edits(session)[-1]) == [f"decision:final_accept:{app_id}", f"decision:back:{app_id}"]

    async def test_summary_survives_ai_outage(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        # AI sozlanmagan (API_URL .invalid): xulosa o'rniga sabablarning o'zi ko'rsatiladi
        app_id = await self._tie(dp, bot)
        await self._click(dp, bot, "accept", app_id)
        text = edit_texts(session)[-1]
        assert "Yoshi kichik" in text and "Qabul qilishni tasdiqlang" in text
        assert_no_errors(session)

    async def test_reject_confirm_shows_yes_count_and_back_returns_to_report(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._tie(dp, bot)
        await self._click(dp, bot, "reject", app_id)
        assert "Rad etishni tasdiqlang" in edit_texts(session)[-1] and "<b>1</b>" in edit_texts(session)[-1]
        assert await status_of(app_id) == "admin_decision"
        await self._click(dp, bot, "back", app_id)
        assert "Rad etishni tasdiqlang" not in edit_texts(session)[-1] and "Ism" in edit_texts(session)[-1]

    async def test_final_accept_then_first_admin_wins(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._tie(dp, bot)
        await self._click(dp, bot, "final_accept", app_id)
        assert await status_of(app_id) == "accepted"
        assert session.of(ApproveChatJoinRequest)[0].user_id == U
        assert session.texts_to(U) == [texts.APPLICATION_ACCEPTED]
        assert any("Qabul qilindi" in t for t in edit_texts(session))
        # boshqa adminga holat xabari boradi, qaror qilganning xabari tahrirlanadi
        other = session.texts_to(tf.ADMIN2_ID)
        assert len(other) == 1 and "guruhga qabul qilindi" in other[0] and "qaror:" in other[0]
        assert not any("guruhga qabul" in t for t in session.texts_to(tf.ADMIN_ID))
        session.clear()
        await self._click(dp, bot, "final_reject", app_id, tf.ADMIN2_ID)
        assert "allaqachon" in alert(session)
        assert await status_of(app_id) == "accepted" and not declined(session)

    async def test_final_reject_sends_soft_note_and_declines(self, dp: Dispatcher, bot: Bot, session: FakeSession, summary_ai: Callable ) -> None:
        summary_ai("Umumiy fikr.")
        app_id = await self._tie(dp, bot)
        await self._click(dp, bot, "final_reject", app_id)
        assert await status_of(app_id) == "rejected" and declined(session)
        note = session.texts_to(U)[0]
        assert "Umumiy fikr" in note and "Yoshi kichik" not in note
        assert "guruhga qabul qilinmadi" in session.texts_to(tf.ADMIN2_ID)[0]

    async def test_simultaneous_final_decisions_apply_once(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._tie(dp, bot)
        await asyncio.gather(
            self._click(dp, bot, "final_accept", app_id), self._click(dp, bot, "final_reject", app_id, tf.ADMIN2_ID)
        )
        assert len(session.texts_to(U)) == 1
        assert await status_of(app_id) in ("accepted", "rejected")

    async def test_invalid_clicks_are_refused(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._tie(dp, bot)
        for action in ("accept", "reject", "final_accept", "final_reject", "back"):
            await self._click(dp, bot, action, app_id, M[0])
            assert "faqat adminlar" in alert(session)
        await self._click(dp, bot, "explode", app_id)  # noma'lum amal
        assert await status_of(app_id) == "admin_decision"
        await self._click(dp, bot, "final_accept", 9999)
        assert "topilmadi" in alert(session)
        # hali "voting"dagi arizada tugmalar ishlamaydi
        other = await voting_app(dp, bot, user=2)
        for action in ("accept", "final_accept", "final_reject"):
            await self._click(dp, bot, action, other)
        assert await status_of(other) == "voting"

    async def test_admin_name_is_escaped_in_result(self, dp: Dispatcher, bot: Bot, session: FakeSession) -> None:
        app_id = await self._tie(dp, bot)
        raw = tf.callback(tf.ADMIN_ID, decision_cb("final_accept", app_id)).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        raw["callback_query"]["from"]["first_name"] = "<i>Admin</i>"
        await dp.feed_raw_update(bot, raw)
        assert "<i>Admin</i>" not in edit_texts(session)[-1]
