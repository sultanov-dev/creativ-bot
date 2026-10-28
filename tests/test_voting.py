"""utils/voting.py: ovoz berish natijasini hisoblash va yakunlash (finalize_due_votings)."""
import asyncio
from typing import Callable

import pytest
from aiogram import Bot
from aiogram.methods import (
    ApproveChatJoinRequest,
    DeclineChatJoinRequest,
    DeleteMessage,
    EditMessageText,
    SendMessage,
)

import database as dbm
import texts
from tests.table import check
from tests.flow import make_voting_app, set_full_name, status_of
from tests.telegram_fakes import (
    ADMIN2_ID,
    ADMIN_ID,
    GROUP_ID,
    FakeSession,
    bad_request,
    forbidden,
    network_error,
    retry_after,
)
from utils import voting
from utils.voting import is_accepted, is_rejected

ADMINS = (ADMIN_ID, ADMIN2_ID)
PHONE = "+998901234567"


def fail_for(session: FakeSession, make: Callable[[SendMessage], BaseException], *chat_ids: int) -> None:
    """Berilgan chatlarga SendMessage `make(m)` xatosi bilan yiqiladi (qolganlariga yetib boradi)."""
    session.errors[SendMessage] = lambda m: make(m) if m.chat_id in chat_ids else None


@pytest.fixture
def no_ai(summary_ai) -> None:
    """AI chaqirilmasin: rad etishda sabab xulosasi bo'sh."""
    summary_ai(None)


class TestThresholds:
    """VOTE_ACCEPT_PERCENT=60 (conftest)."""

    def test_matrix(self):
        check(lambda yes, no: (is_accepted(yes, no), is_rejected(yes, no)), [
            ((0, 0), (False, False)),
            ((1, 0), (True, False)),
            ((0, 1), (False, True)),
            ((3, 2), (True, False)),  # 60% aniq chegarada qabul (butun son hisobi)
            ((2, 3), (False, True)),  # "yo'q" 60% ga yetdi -> rad
            ((1, 1), (False, False)),
            ((59, 41), (False, False)),
            ((60, 40), (True, False)),
            ((40, 60), (False, True)),
            ((41, 59), (False, False)),
            ((299, 201), (False, False)),  # 59.8%
            ((300, 200), (True, False)),
            ((100, 0), (True, False)),
            ((0, 100), (False, True)),
        ])

    def test_low_percent(self, monkeypatch):
        """Past foizda ham: durang hech kimga yetmaydi (adminlarga), ozchilik hech qachon qabul qilinmaydi."""
        for percent in (1, 20, 40, 50):
            monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", percent)
            assert not is_accepted(5, 5) and not is_rejected(5, 5)
            for yes, no in [(1, 2), (2, 3), (4, 5), (0, 1)]:
                assert not is_accepted(yes, no) and is_rejected(yes, no), (percent, yes, no)
            for yes, no in [(2, 1), (3, 2), (5, 4)]:
                assert is_accepted(yes, no) and not is_rejected(yes, no), (percent, yes, no)


def test_report_text_is_anketa_plus_escaped_phone():
    app = {"anketa": "👤 <b>Ism:</b> A B\n", "phone": None}
    assert voting.report_text(app) == app["anketa"]  # ortiqcha sarlavha, foiz yoki ovoz soni yo'q
    t = voting.report_text({**app, "phone": "<b>x</b>"})
    assert "&lt;b&gt;x&lt;/b&gt;" in t and "<b>x</b>" not in t.split("Telefon:</b>")[1].split("\n")[0]


class TestFinalize:
    async def test_still_running_is_untouched(self, db, bot, session):
        app_id = await make_voting_app(expired=False)
        assert await voting.finalize_due_votings(bot) == 0
        assert await status_of(app_id) == "voting" and session.requests == []

    @pytest.mark.parametrize(
        "votes,status,user_note,admin_text",
        [
            ([], "expired", "hech kim ovoz bermadi", "❌ <b>Aziz Karimov</b> guruhga qabul qilinmadi: hech kim ovoz bermadi"),
            (["yes"] * 3 + ["no"] * 2, "accepted", texts.APPLICATION_ACCEPTED, "✅ <b>Aziz Karimov</b> guruhga qabul qilindi"),
            (["no"] * 3 + ["yes"], "rejected", texts.APPLICATION_REJECTED, "❌ <b>Aziz Karimov</b> guruhga qabul qilinmadi"),
        ],
    )
    async def test_final_outcome(self, db, bot, session, no_ai, votes, status, user_note, admin_text):
        """Yakun: join request hal qilinadi, ovoz xabari o'chadi, arizachiga va har bir adminga status boradi."""
        app_id = await make_voting_app(votes=votes)
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == status
        approve = session.of(ApproveChatJoinRequest)
        assert [(m.chat_id, m.user_id) for m in approve] == ([(GROUP_ID, 1)] if status == "accepted" else [])
        assert bool(session.of(DeclineChatJoinRequest)) == (status != "accepted")
        assert user_note in session.texts_to(1)[0]
        assert session.of(DeleteMessage)[0].message_id == 500
        for admin in ADMINS:
            assert session.texts_to(admin) == [admin_text]

    async def test_rejection_note_never_contains_raw_reasons(self, db, bot, session, summary_ai):
        app_id = await make_voting_app(votes=["no", "no", "no"])
        await dbm.set_vote_reason(app_id, 100, "SIRLI-SABAB-12345")
        summary_ai("Umumiy fikr: anketa batafsilroq bo'lsin.")
        await voting.finalize_due_votings(bot)
        text = session.texts_to(1)[0]
        assert "SIRLI-SABAB" not in text
        assert texts.FEEDBACK_INTRO in text and "batafsilroq" in text

    async def test_tie_goes_to_admins_with_phone_but_group_never_sees_it(self, db, bot, session):
        app_id = await make_voting_app(votes=["yes", "yes", "no", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "admin_decision"
        assert not session.of(ApproveChatJoinRequest) and not session.of(DeclineChatJoinRequest)
        for admin in ADMINS:
            sent = session.sent_to(admin)  # status emas, faqat qaror hisoboti
            assert len(sent) == 1 and sent[0].reply_markup is not None
            assert PHONE in sent[0].text
        assert "adminlar qabul qiladi" in session.texts_to(1)[0]
        assert all(PHONE not in m.text for m in session.sent_to(GROUP_ID))

    @pytest.mark.parametrize(
        "errors,msg_id,deleted,edited",
        [
            ((), 777, True, False),
            ((DeleteMessage,), 777, True, True),  # o'chmasa natija bilan tahrirlanadi
            ((DeleteMessage, EditMessageText), 777, True, True),  # ikkalasi yiqilsa ham ariza yopiladi
            ((), None, False, False),  # ovoz xabari id'si yo'q
        ],
    )
    async def test_vote_message_cleanup(self, db, bot, session, errors, msg_id, deleted, edited):
        for method in errors:
            session.errors[method] = bad_request("message can't be deleted")
        app_id = await make_voting_app(vote_message_id=msg_id, votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "accepted"
        assert [(m.chat_id, m.message_id) for m in session.of(DeleteMessage)] == ([(GROUP_ID, 777)] if deleted else [])
        edits = session.of(EditMessageText)
        assert bool(edits) == edited and (not edits or edits[0].message_id == 777)

    async def test_approve_failure_is_swallowed(self, db, bot, session):
        session.errors[ApproveChatJoinRequest] = bad_request("HIDE_REQUESTER_MISSING")
        app_id = await make_voting_app(votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "accepted"
        assert session.texts_to(1)  # arizachiga baribir xabar ketadi

    @pytest.mark.parametrize("make", [forbidden, retry_after])
    async def test_user_notification_error_does_not_stop_other_applications(self, db, bot, session, make):
        fail_for(session, make, 1)
        a = await make_voting_app(user_id=1, vote_message_id=1, votes=["yes"])
        b = await make_voting_app(user_id=2, vote_message_id=2, votes=["yes"])
        assert await voting.finalize_due_votings(bot) == 2
        assert await status_of(a) == await status_of(b) == "accepted"

    async def test_second_and_concurrent_runs_process_once(self, db, bot, session):
        await make_voting_app(user_id=1, vote_message_id=1, votes=["yes"])
        await make_voting_app(user_id=2, vote_message_id=2, votes=["yes"])
        results = await asyncio.gather(voting.finalize_due_votings(bot), voting.finalize_due_votings(bot))
        assert sum(results) == 2 and len(session.of(ApproveChatJoinRequest)) == 2
        session.clear()
        assert await voting.finalize_due_votings(bot) == 0 and session.requests == []

    async def test_several_applications_processed_independently(self, db, bot, session, no_ai):
        ids = [
            await make_voting_app(user_id=1, vote_message_id=1, votes=["yes"]),
            await make_voting_app(user_id=2, vote_message_id=2, votes=["no"]),
            await make_voting_app(user_id=3, vote_message_id=3, votes=[]),
            await make_voting_app(user_id=4, vote_message_id=4, votes=["yes", "no"]),
        ]
        assert await voting.finalize_due_votings(bot) == 4
        assert [await status_of(x) for x in ids] == ["accepted", "rejected", "expired", "admin_decision"]

    @pytest.mark.parametrize(
        "percent,votes,status",
        [(40, ["yes", "yes", "no", "no", "no"], "rejected"), (50, ["yes", "no"], "admin_decision")],
    )
    async def test_low_percent_outcome(self, db, bot, session, monkeypatch, no_ai, percent, votes, status):
        monkeypatch.setattr(voting, "VOTE_ACCEPT_PERCENT", percent)
        app_id = await make_voting_app(votes=votes)
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == status
        assert not session.of(ApproveChatJoinRequest)


class TestAdminStatus:
    """Adminlarga status matni (asosiy matnlar test_final_outcome da)."""

    async def test_name_is_html_escaped(self, db, bot, session):
        app_id = await make_voting_app(votes=["yes", "yes", "yes"])
        await set_full_name(app_id, "<b>X</b> Y")
        await voting.finalize_due_votings(bot)
        text = session.texts_to(ADMIN_ID)[0]
        assert "&lt;b&gt;X&lt;/b&gt; Y" in text and "<b>X</b> Y" not in text


class TestPerformance:
    async def test_group_work_does_not_wait_for_slow_ai(self, db, bot, session, monkeypatch):
        """Rad etilganda so'rov rad etiladi va ovoz xabari o'chadi, AI xulosasi esa shundan keyin keladi."""
        order: list[str] = []

        async def slow_feedback(reasons):
            order.append("ai")

        async def decline(*a, **k):
            order.append("decline")
            return await real_decline(*a, **k)

        real_decline = bot.decline_chat_join_request
        monkeypatch.setattr(voting, "feedback_for_applicant", slow_feedback)
        monkeypatch.setattr(bot, "decline_chat_join_request", decline, raising=False)
        await make_voting_app(votes=["no", "no", "no"])
        await voting.finalize_due_votings(bot)
        assert order.index("decline") < order.index("ai")

    async def test_slow_ai_for_one_application_does_not_block_others(self, db, bot, session, monkeypatch):
        gate = asyncio.Event()
        started: list[int] = []

        async def feedback(reasons):
            started.append(1)
            if len(started) == 1:
                await gate.wait()  # birinchisi "osilib" turadi
            else:
                gate.set()  # ikkinchisi yetib kelsa, birinchini qo'yib yuboradi

        monkeypatch.setattr(voting, "feedback_for_applicant", feedback)
        await make_voting_app(user_id=1, vote_message_id=501, votes=["no"] * 3)
        await make_voting_app(user_id=2, vote_message_id=502, votes=["no"] * 3)
        # ketma-ket bo'lganida bu test osilib qolardi (birinchi AI ikkinchisini kutdirardi)
        assert await asyncio.wait_for(voting.finalize_due_votings(bot), 5) == 2

    async def test_one_failing_application_does_not_stop_the_others(self, db, bot, session, monkeypatch):
        calls: list[int] = []
        real = voting._finalize_one

        async def flaky(b: Bot, app: dict):
            calls.append(app["id"])
            if len(calls) == 1:
                raise RuntimeError("kutilmagan xato")
            return await real(b, app)

        monkeypatch.setattr(voting, "_finalize_one", flaky)
        await make_voting_app(user_id=1, vote_message_id=501, votes=["yes"] * 3)
        await make_voting_app(user_id=2, vote_message_id=502, votes=["yes"] * 3)
        assert await voting.finalize_due_votings(bot) == 1


class TestAdminDeliveryFallbacks:
    @pytest.mark.parametrize(
        "votes,status",
        [(["yes", "yes", "no", "no", "yes"], "accepted"), (["yes", "no"], "rejected")],
    )
    async def test_no_admins_configured_majority_decides(self, db, bot, session, monkeypatch, no_ai, votes, status):
        import utils.admin as admin_utils

        monkeypatch.setattr(admin_utils, "ADMIN_IDS", [])
        app_id = await make_voting_app(votes=votes)
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == status

    @pytest.mark.parametrize(
        "make,votes,status,note",
        [
            (forbidden, ["yes"] * 4 + ["no"] * 3, "accepted", texts.APPLICATION_ACCEPTED),  # 57%: ko'pchilik qabul
            (forbidden, ["yes", "no"], "rejected", texts.APPLICATION_REJECTED),  # durang -> rad
            (bad_request, ["yes"] * 3 + ["no"] * 4, "rejected", texts.APPLICATION_REJECTED),  # 43% / 57%
        ],
    )
    async def test_unreachable_admins_majority_decides(
        self, db, bot, session, no_ai, make, votes, status, note
    ):
        fail_for(session, make, *ADMINS)
        app_id = await make_voting_app(votes=votes)
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == status
        assert bool(session.of(ApproveChatJoinRequest)) == (status == "accepted")
        assert bool(session.of(DeclineChatJoinRequest)) == (status == "rejected")
        assert session.texts_to(1) == [note]

    @pytest.mark.parametrize("make", [retry_after, lambda m: RuntimeError("aiohttp"), network_error])
    async def test_transient_error_keeps_voting_and_retries(self, db, bot, session, make):
        fail_for(session, make, *ADMINS)
        app_id = await make_voting_app(votes=["yes", "no"])
        assert await voting.finalize_due_votings(bot) == 0
        assert await status_of(app_id) == "voting"
        # xabar o'chirilmagan va arizachiga hech narsa yozilmagan
        assert not session.of(DeleteMessage) and not session.texts_to(1)
        session.errors.clear()  # keyingi tsiklda qayta uriniladi
        assert await voting.finalize_due_votings(bot) == 1
        assert await status_of(app_id) == "admin_decision"

    @pytest.mark.parametrize("make", [forbidden, retry_after])
    async def test_one_admin_reachable_is_enough(self, db, bot, session, make):
        fail_for(session, make, ADMIN_ID)
        app_id = await make_voting_app(votes=["yes", "no"])
        await voting.finalize_due_votings(bot)
        assert await status_of(app_id) == "admin_decision"
        assert len(session.sent_to(ADMIN2_ID)) == 1


async def test_rejection_note_without_reasons_is_plain(db, monkeypatch):
    app_id = await make_voting_app(votes=["no"])
    called: list = []

    async def spy(reasons):
        called.append(reasons)

    monkeypatch.setattr(voting, "feedback_for_applicant", spy)
    assert await voting.rejection_note(app_id) == texts.APPLICATION_REJECTED
    assert called == [[None]]


async def test_ai_gateway_garbage_must_not_break_finalize(db, bot, session, monkeypatch):
    """AI shlyuzi 200 + yaroqsiz JSON qaytarsa ham ariza yopiladi, arizachi xabar oladi, qolganlari ishlanadi."""
    import utils.ai as ai_mod
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    async def garbage(request: web.Request) -> web.Response:
        return web.Response(text="<html>502</html>", content_type="text/html")

    server_app = web.Application()
    server_app.router.add_post("/x", garbage)
    server = TestServer(server_app, host="127.0.0.1")
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
