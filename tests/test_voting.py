"""utils/voting.py: ovoz berish natijasini hisoblash va yakunlash (finalize_due_votings)."""
import asyncio

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import (
    ApproveChatJoinRequest,
    DeclineChatJoinRequest,
    DeleteMessage,
    EditMessageText,
    SendMessage,
)

import database as dbm
import texts
from tests.conftest import expire_voting
from tests.telegram_fakes import ADMIN2_ID, ADMIN_ID, GROUP_ID
from utils import voting
from utils.voting import is_accepted, is_rejected


def bad_request(msg="Bad Request: x"):
    return TelegramBadRequest(method=None, message=msg)


def forbidden():
    return TelegramForbiddenError(method=None, message="Forbidden: bot was blocked by the user")


def retry_after():
    return TelegramRetryAfter(method=None, message="Flood", retry_after=1)


def network_error():
    return TelegramNetworkError(method=None, message="boom")


class TestThresholds:
    """VOTE_ACCEPT_PERCENT=60 (conftest)."""

    @pytest.mark.parametrize(
        "yes,no,accepted,rejected",
        [
            (0, 0, False, False),
            (1, 0, True, False),
            (0, 1, False, True),
            (3, 2, True, False),  # 60% aniq chegarada qabul
            (2, 3, False, True),  # 40% / 60%: "yo'q" 60% ga yetdi -> rad
            (1, 1, False, False),
            (59, 41, False, False),
            (60, 40, True, False),
            (40, 60, False, True),
            (41, 59, False, False),
            (6, 4, True, False),
            (4, 6, False, True),
            (100, 0, True, False),
            (0, 100, False, True),
        ],
    )
    def test_matrix(self, yes, no, accepted, rejected):
        assert is_accepted(yes, no) is accepted
        assert is_rejected(yes, no) is rejected

    def test_exact_boundary_uses_integer_math(self):
        # 3/5 = 60% aniq: floating point xatosi bo'lmasligi kerak
        assert is_accepted(3, 2)
        assert not is_accepted(299, 201)  # 59.8%
        assert is_accepted(300, 200)

    def test_zero_total_never_accepts_or_rejects(self):
        assert not is_accepted(0, 0) and not is_rejected(0, 0)

    def test_gap_between_thresholds_exists_with_default_percent(self):
        # 50/50 ikkala tomon ham yetmaydi -> admin qarori
        assert not is_accepted(5, 5) and not is_rejected(5, 5)

    @pytest.mark.parametrize("percent", [1, 20, 40, 50])
    def test_low_percent_tie_is_neither_accepted_nor_rejected(self, monkeypatch, percent):
        """VOTE_ACCEPT_PERCENT <= 50 bo'lsa ham ikki tomon bir vaqtda "yetmaydi": durang adminlarga ketadi."""
        monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", percent)
        assert not is_accepted(5, 5) and not is_rejected(5, 5)

    @pytest.mark.parametrize("percent", [1, 20, 40, 50])
    @pytest.mark.parametrize("yes,no", [(1, 2), (2, 3), (4, 5), (0, 1)])
    def test_low_percent_minority_is_never_accepted(self, monkeypatch, percent, yes, no):
        monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", percent)
        assert not is_accepted(yes, no)
        assert is_rejected(yes, no)

    @pytest.mark.parametrize("yes,no", [(2, 1), (3, 2), (5, 4)])
    def test_low_percent_majority_yes_is_accepted(self, monkeypatch, yes, no):
        monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", 40)
        assert is_accepted(yes, no) and not is_rejected(yes, no)

    def test_majority_no_should_never_be_auto_accepted(self, monkeypatch):
        monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", 40)
        yes, no = 2, 3  # yes ulushi 40%
        assert not (is_accepted(yes, no) and no > yes)


class TestReportText:
    APP = {"anketa": "👤 <b>Ism:</b> A B\n", "phone": None}

    def test_without_phone(self):
        t = voting.report_text(self.APP)
        assert t == self.APP["anketa"]  # ortiqcha sarlavha, foiz yoki ovoz soni yo'q

    def test_phone_is_html_escaped(self):
        t = voting.report_text({**self.APP, "phone": "<b>x</b>"})
        assert "&lt;b&gt;x&lt;/b&gt;" in t and "<b>x</b>" not in t.split("Telefon:</b>")[1].split("\n")[0]


# ---------------------------------------------------------------- finalize_due_votings


async def make_voting_app(user_id=1, group_id=GROUP_ID, vote_message_id=500, votes=()):
    app_id = await dbm.create_application(user_id, group_id, "Aziz Karimov", "ANKETA\n", phone="+998901234567")
    await dbm.start_voting(app_id, 10)
    if vote_message_id:
        await dbm.set_vote_message(app_id, vote_message_id)
    for i, v in enumerate(votes):
        await dbm.add_vote(app_id, 100 + i, v)
    await expire_voting(app_id)
    return app_id


async def status_of(app_id):
    return (await dbm.get_application(app_id))["status"]


@pytest.fixture
def no_ai(monkeypatch):
    """AI chaqirilmasin: rad etishda sabab xulosasi bo'sh."""

    async def fake(reasons):
        return None

    monkeypatch.setattr(voting, "feedback_for_applicant", fake)


class TestFinalize:
    async def test_nothing_due(self, db, bot):
        assert await voting.finalize_due_votings(bot) == 0

    async def test_voting_still_running_is_untouched(self, db, bot, session):
        app_id = await dbm.create_application(1, GROUP_ID, "A B", "x\n")
        await dbm.start_voting(app_id, 10)
        assert await voting.finalize_due_votings(bot) == 0
        assert await status_of(app_id) == "voting" and session.requests == []

    async def test_zero_votes_expires_and_declines(self, db, bot, session):
        app_id = await make_voting_app()
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "expired"
        assert session.of(DeclineChatJoinRequest) and not session.of(ApproveChatJoinRequest)
        assert "hech kim ovoz bermadi" in session.texts_to(1)[0]
        assert session.of(DeleteMessage)[0].message_id == 500

    async def test_accepted_approves_join_request_and_notifies(self, db, bot, session):
        app_id = await make_voting_app(votes=["yes", "yes", "yes", "no", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted"
        approve = session.of(ApproveChatJoinRequest)[0]
        assert (approve.chat_id, approve.user_id) == (GROUP_ID, 1)
        assert session.texts_to(1) == [texts.APPLICATION_ACCEPTED]

    async def test_rejected_declines_and_sends_soft_note(self, db, bot, session, no_ai):
        app_id = await make_voting_app(votes=["no", "no", "no", "yes"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "rejected"
        assert session.of(DeclineChatJoinRequest)
        assert session.texts_to(1) == [texts.APPLICATION_REJECTED]

    async def test_rejection_note_never_contains_raw_reasons(self, db, bot, session, monkeypatch):
        app_id = await make_voting_app(votes=["no", "no", "no"])
        await dbm.set_vote_reason(app_id, 100, "SIRLI-SABAB-12345")

        async def fake_ai(messages):
            return "Umumiy fikr: anketa batafsilroq bo'lsin."

        import utils.summary as summary

        monkeypatch.setattr(summary, "ask_ai", fake_ai)
        await voting.finalize_due_votings(bot)
        text = session.texts_to(1)[0]
        assert "SIRLI-SABAB" not in text
        assert texts.FEEDBACK_INTRO in text and "batafsilroq" in text

    async def test_tie_goes_to_admins_with_buttons(self, db, bot, session):
        app_id = await make_voting_app(votes=["yes", "yes", "no", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "creator_review"
        assert not session.of(ApproveChatJoinRequest) and not session.of(DeclineChatJoinRequest)
        for admin in (ADMIN_ID, ADMIN2_ID):
            sent = session.sent_to(admin)
            assert len(sent) == 1 and sent[0].reply_markup is not None
            assert "+998901234567" in sent[0].text  # adminlar telefonni ko'radi
        assert "adminlar qabul qiladi" in session.texts_to(1)[0]

    async def test_group_message_never_contains_phone(self, db, bot, session):
        await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert all("+998901234567" not in m.text for m in session.sent_to(GROUP_ID))

    async def test_vote_message_deleted_after_finish(self, db, bot, session):
        await make_voting_app(vote_message_id=777, votes=["yes"])
        await voting.finalize_due_votings(bot)
        d = session.of(DeleteMessage)
        assert d and (d[0].chat_id, d[0].message_id) == (GROUP_ID, 777)
        assert not session.of(EditMessageText)

    async def test_if_delete_fails_message_is_edited_with_result(self, db, bot, session):
        session.errors[DeleteMessage] = bad_request("message can't be deleted")
        await make_voting_app(vote_message_id=777, votes=["yes"])
        await voting.finalize_due_votings(bot)
        edit = session.of(EditMessageText)[0]
        assert edit.message_id == 777 and "Qabul qilindi" in edit.text

    async def test_if_delete_and_edit_both_fail_nothing_crashes(self, db, bot, session):
        session.errors[DeleteMessage] = bad_request()
        session.errors[EditMessageText] = bad_request()
        app_id = await make_voting_app(votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "accepted"

    async def test_no_vote_message_id_skips_delete(self, db, bot, session):
        await make_voting_app(vote_message_id=None, votes=["yes"])
        await voting.finalize_due_votings(bot)
        assert not session.of(DeleteMessage) and not session.of(EditMessageText)

    async def test_approve_failure_is_swallowed(self, db, bot, session):
        session.errors[ApproveChatJoinRequest] = bad_request("HIDE_REQUESTER_MISSING")
        app_id = await make_voting_app(votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "accepted"
        assert session.texts_to(1)  # arizachiga baribir xabar ketadi

    async def test_user_blocked_bot_does_not_stop_other_applications(self, db, bot, session):
        session.errors[SendMessage] = lambda m: forbidden() if m.chat_id == 1 else None
        a = await make_voting_app(user_id=1, vote_message_id=1, votes=["yes"])
        b = await make_voting_app(user_id=2, vote_message_id=2, votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 2
        assert await status_of(a) == "accepted" and await status_of(b) == "accepted"

    async def test_flood_limit_on_user_notification_does_not_abort_loop(self, db, bot, session):
        session.errors[SendMessage] = lambda m: retry_after() if m.chat_id == 1 else None
        await make_voting_app(user_id=1, vote_message_id=1, votes=["yes"])
        b = await make_voting_app(user_id=2, vote_message_id=2, votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 2
        assert await status_of(b) == "accepted"

    async def test_second_run_is_a_noop(self, db, bot, session):
        await make_voting_app(votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 1
        session.clear()
        assert await voting.finalize_due_votings(bot) == 0
        assert session.requests == []

    async def test_concurrent_finalizers_process_once(self, db, bot, session):
        app_id = await make_voting_app(votes=["yes"])
        results = await asyncio.gather(voting.finalize_due_votings(bot), voting.finalize_due_votings(bot))
        assert sorted(results) == [0, 1]
        assert len(session.of(ApproveChatJoinRequest)) == 1

    async def test_several_applications_processed_independently(self, db, bot, session, no_ai):
        a = await make_voting_app(user_id=1, vote_message_id=1, votes=["yes"])
        b = await make_voting_app(user_id=2, vote_message_id=2, votes=["no"])
        c = await make_voting_app(user_id=3, vote_message_id=3, votes=[])
        d = await make_voting_app(user_id=4, vote_message_id=4, votes=["yes", "no"])
        assert await voting.finalize_due_votings(bot) == 4
        assert [await status_of(x) for x in (a, b, c, d)] == ["accepted", "rejected", "expired", "creator_review"]


class TestAdminDeliveryFallbacks:
    async def test_no_admins_configured_majority_yes_accepts(self, db, bot, session, monkeypatch):
        monkeypatch.setattr(voting, "ADMIN_IDS", [])
        app_id = await make_voting_app(votes=["yes", "yes", "no", "no", "yes"])  # 3/5 = 60%: avtomatik qabul
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted"

    async def test_no_admins_configured_tie_is_rejected(self, db, bot, session, monkeypatch, no_ai):
        monkeypatch.setattr(voting, "ADMIN_IDS", [])
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "rejected"

    async def test_unreachable_admins_majority_decides_accept(self, db, bot, session):
        session.errors[SendMessage] = lambda m: forbidden() if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        # 4 yes / 3 no: 57% -> ikkala tomon yetmaydi, adminlarga yetib bo'lmaydi -> ko'pchilik (yes>no) qabul
        app_id = await make_voting_app(votes=["yes"] * 4 + ["no"] * 3)
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "accepted"
        assert session.of(ApproveChatJoinRequest)
        assert session.texts_to(1) == [texts.APPLICATION_ACCEPTED]

    async def test_unreachable_admins_tie_is_rejected(self, db, bot, session, no_ai):
        session.errors[SendMessage] = lambda m: forbidden() if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "rejected"
        assert session.of(DeclineChatJoinRequest)
        assert session.texts_to(1) == [texts.APPLICATION_REJECTED]

    async def test_unreachable_admins_minority_yes_rejected(self, db, bot, session, no_ai):
        session.errors[SendMessage] = lambda m: bad_request() if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        app_id = await make_voting_app(votes=["yes"] * 3 + ["no"] * 4)  # 43% / 57%
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "rejected"

    async def test_transient_error_keeps_voting_for_retry(self, db, bot, session):
        session.errors[SendMessage] = lambda m: retry_after() if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        app_id = await make_voting_app(votes=["yes", "no"])
        assert await voting.finalize_due_votings(bot) == 0
        assert await status_of(app_id) == "voting"
        # xabar o'chirilmagan va arizachiga hech narsa yozilmagan
        assert not session.of(DeleteMessage) and not session.texts_to(1)

    async def test_retry_succeeds_next_cycle(self, db, bot, session):
        session.errors[SendMessage] = lambda m: retry_after() if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        session.errors.clear()
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "creator_review"

    async def test_one_admin_reachable_is_enough(self, db, bot, session):
        session.errors[SendMessage] = lambda m: forbidden() if m.chat_id == ADMIN_ID else None
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "creator_review"
        assert len(session.sent_to(ADMIN2_ID)) == 1

    async def test_reachable_plus_flaky_admin_counts_as_sent(self, db, bot, session):
        session.errors[SendMessage] = lambda m: retry_after() if m.chat_id == ADMIN_ID else None
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "creator_review"

    async def test_non_telegram_error_while_notifying_admins_is_retried(self, db, bot, session):
        session.errors[SendMessage] = lambda m: RuntimeError("aiohttp") if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        app_id = await make_voting_app(votes=["yes", "no"])
        assert await voting.finalize_due_votings(bot) == 0
        assert await status_of(app_id) == "voting"

    async def test_network_error_to_admin_is_retry(self, db, bot, session):
        session.errors[SendMessage] = lambda m: network_error() if m.chat_id in (ADMIN_ID, ADMIN2_ID) else None
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "voting"


async def test_rejection_note_without_reasons_is_plain(db, monkeypatch):
    app_id = await make_voting_app(votes=["no"])
    called = []

    async def spy(reasons):
        called.append(reasons)
        return None

    monkeypatch.setattr(voting, "feedback_for_applicant", spy)
    assert await voting.rejection_note(app_id) == texts.APPLICATION_REJECTED
    assert called == [[None]]


async def test_ai_gateway_garbage_must_not_break_finalize(db, bot, session, monkeypatch):
    """AI shlyuzi 200 + yaroqsiz JSON qaytarsa ham ariza yopiladi, arizachi xabar oladi, qolganlari ishlanadi."""
    import utils.ai as ai_mod
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def garbage(request):
        return web.Response(text="<html>502</html>", content_type="text/html")

    app = web.Application()
    app.router.add_post("/x", garbage)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    try:
        monkeypatch.setattr(ai_mod, "API_URL", f"http://127.0.0.1:{server.port}/x")
        rejected = await make_voting_app(user_id=1, vote_message_id=1, votes=["no", "no", "no"])
        await dbm.set_vote_reason(rejected, 100, "sabab")
        other = await make_voting_app(user_id=2, vote_message_id=2, votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 2
        assert session.texts_to(1) == [texts.APPLICATION_REJECTED]
        assert await status_of(other) == "accepted"
    finally:
        await server.close()


async def test_low_percent_majority_no_is_rejected_not_accepted(db, bot, session, monkeypatch, no_ai):
    monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", 40)
    app_id = await make_voting_app(votes=["yes", "yes", "no", "no", "no"])
    await voting.finalize_due_votings(bot)
    assert await status_of(app_id) == "rejected"
    assert not session.of(ApproveChatJoinRequest)


async def test_low_percent_tie_goes_to_admins(db, bot, session, monkeypatch):
    monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", 50)
    app_id = await make_voting_app(votes=["yes", "no"])
    await voting.finalize_due_votings(bot)
    assert await status_of(app_id) == "creator_review"
