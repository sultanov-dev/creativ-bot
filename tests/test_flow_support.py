"""handlers/support.py: guruhda contact_admin chaqirilganda lichkaga yozish va guruhdagi qisqa xabar."""
import pytest
from aiogram.methods import SendChatAction, SendMessage

import handlers.ai as ai_handler
import handlers.support as support
import texts
from config import ADMIN_IDS
from database import get_support_chat
from tests import telegram_fakes as tf
from tests.flow import feed
from tests.test_flow_ai import BOT, USER, FakeAsk, bot_replies, say
from utils import support_policy


@pytest.fixture
def group_ai(monkeypatch: pytest.MonkeyPatch) -> FakeAsk:
    """Guruhdagi AI contact_admin tool'ini chaqiradi."""
    fake = FakeAsk()
    fake.answer = ""
    fake.tool_calls = [("contact_admin", {"reason": "admin kerak"})]
    monkeypatch.setattr(ai_handler, "ask_ai_tools", fake)
    return fake


@pytest.fixture
def dm_ai(monkeypatch: pytest.MonkeyPatch) -> FakeAsk:
    """Lichkadagi AI: birinchi xabar."""
    fake = FakeAsk()
    fake.answer = "Salom! Nima bo'ldi?"
    monkeypatch.setattr(support, "ask_ai_tools", fake)
    return fake


class TestContactAdmin:
    async def test_dm_is_sent_and_group_gets_short_notice(self, dp, bot, session, group_ai, dm_ai):
        await say(dp, bot, f"{BOT} admin bilan gaplashmoqchiman")
        assert session.texts_to(USER) == ["Salom! Nima bo'ldi?"]
        assert [m.text for m in bot_replies(session)] == [texts.SUPPORT_DM_SENT["uz"]]
        assert await get_support_chat(USER, "active", 24) is not None

    async def test_notice_follows_the_language_of_the_message(self, dp, bot, session, group_ai, dm_ai):
        await say(dp, bot, f"{BOT} I want to talk to the admin, please")
        assert [m.text for m in bot_replies(session)] == [texts.SUPPORT_DM_SENT["en"]]

    async def test_user_who_never_pressed_start_is_asked_to_do_so(self, dp, bot, session, group_ai, dm_ai):
        session.errors[SendChatAction] = tf.forbidden()
        await say(dp, bot, f"{BOT} admin bilan gaplashmoqchiman")
        replies = [m.text for m in bot_replies(session)]
        assert len(replies) == 1 and replies[0].startswith("Avval botga /start bosing:")
        assert texts.SUPPORT_DM_SENT["uz"] not in replies
        assert not session.sent_to(USER) and not dm_ai.calls
        assert await get_support_chat(USER, "awaiting_start", 24) is not None


# ---- gatekeeper: adminga faqat toza va haq masalalar boradi

@pytest.fixture(autouse=True)
def _moderation(monkeypatch: pytest.MonkeyPatch):
    """Haqiqiy AI moderatsiyasi o'rniga: matnda 'BADWORD' bo'lsa odobsiz."""

    async def fake(text: str) -> bool:
        return "BADWORD" in text

    monkeypatch.setattr(support, "is_abusive", fake)


async def dm(dp, bot, text: str) -> None:
    await feed(dp, bot, tf.private_message(USER, text))


async def start_chat(dp, bot, group_ai, dm_ai, text: str = f"{BOT} admin bilan gaplashmoqchiman") -> None:
    """Guruhdan lichkaga o'tish; keyin dm_ai ni sinov o'zi sozlaydi."""
    ai_handler._last_ask.clear()  # guruhdagi 5 soniyalik cooldown testni to'smasin
    await say(dp, bot, text)
    dm_ai.calls.clear()


def admin_notices(session) -> list[str]:
    return [t for a in ADMIN_IDS for t in session.texts_to(a)]


class TestGatekeeper:
    async def test_escalation_reaches_admins_without_category_label(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Adminga yubordim."
        dm_ai.tool_calls = [("escalate_to_admin", {"summary": "Tolov qaytmadi", "category": "payment"})]
        await dm(dp, bot, "Pulim qaytmadi")
        notices = admin_notices(session)
        assert len(notices) == len(ADMIN_IDS) and "Tolov qaytmadi" in notices[0]
        assert "payment" not in notices[0] and "ategoriya" not in notices[0]
        chat = await get_support_chat(USER, "escalated", 24)
        assert chat is not None and chat["category"] == "payment"

    async def test_decline_keeps_the_matter_from_admins_and_logs_the_category(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Bunday reklamani qabul qilmaymiz."
        dm_ai.tool_calls = [("decline", {"category": "prohibited_ad"})]
        await dm(dp, bot, "Kazino reklamasini bermoqchiman")
        assert not admin_notices(session)
        assert session.texts_to(USER)[-1] == "Bunday reklamani qabul qilmaymiz."
        chat = await get_support_chat(USER, "declined", 24)
        assert chat is not None and chat["category"] == "prohibited_ad"

    async def test_decline_without_text_sends_the_generic_refusal(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = ""
        dm_ai.tool_calls = [("decline", {"category": "no_purpose"})]
        await dm(dp, bot, "admin kerak")
        assert session.texts_to(USER)[-1] == texts.SUPPORT_DECLINED["uz"] and not admin_notices(session)

    async def test_unknown_categories_fall_back_safely(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = ""
        dm_ai.tool_calls = [("decline", {"category": "xyz"}), ("escalate_to_admin", {"summary": "s", "category": "other"})]
        await dm(dp, bot, "gap")
        assert not admin_notices(session)  # ikkalasi bo'lsa, xavfsizi: rad
        assert (await get_support_chat(USER, "declined", 24))["category"] == "unclear"

    async def test_abusive_message_gets_one_warning_then_decline(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        await dm(dp, bot, "BADWORD adminlar")
        assert session.texts_to(USER)[-1] == texts.SUPPORT_REPHRASE["uz"] and not dm_ai.calls
        await dm(dp, bot, "BADWORD yana")
        assert session.texts_to(USER)[-1] == texts.SUPPORT_DECLINED["uz"] and not dm_ai.calls
        assert (await get_support_chat(USER, "declined", 24))["category"] == "abuse" and not admin_notices(session)

    async def test_abusive_text_never_enters_the_history(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        await dm(dp, bot, "BADWORD birinchi")
        dm_ai.answer = ""
        dm_ai.tool_calls = [("escalate_to_admin", {"summary": "Shikoyat", "category": "complaint"})]
        await dm(dp, bot, "Aslida a'zo meni xafa qildi")
        sent = [m["content"] for m in dm_ai.calls[-1]]
        assert not any("BADWORD" in c for c in sent)
        assert any("a'zo meni xafa qildi" in c for c in sent)

    async def test_abusive_group_message_is_replaced_by_a_placeholder(self, dp, bot, session, group_ai, dm_ai):
        await say(dp, bot, f"{BOT} BADWORD admin bilan gaplashmoqchiman")
        first = dm_ai.calls[0]
        assert not any("BADWORD" in m["content"] for m in first)
        assert any(m["content"].startswith("[Guruhdagi xabar]") for m in first)

    async def test_daily_escalation_limit(self, dp, bot, session, group_ai, dm_ai):
        for _ in range(support_policy.MAX_ESCALATIONS_PER_DAY):
            await start_chat(dp, bot, group_ai, dm_ai)
            dm_ai.answer = ""
            dm_ai.tool_calls = [("escalate_to_admin", {"summary": "s", "category": "other"})]
            await dm(dp, bot, "masala")
            dm_ai.tool_calls = []
            # yangi suhbat ochish uchun oldingisini yopamiz (escalated bo'lib qoladi, soni hisoblanadi)
        session.clear()
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = ""
        dm_ai.tool_calls = [("escalate_to_admin", {"summary": "s", "category": "other"})]
        await dm(dp, bot, "yana masala")
        assert not admin_notices(session)
        assert session.texts_to(USER)[-1] == texts.SUPPORT_LIMIT["uz"]

    async def test_recently_declined_user_gets_a_short_refusal_without_ai(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = ""
        dm_ai.tool_calls = [("decline", {"category": "scam"})]
        await dm(dp, bot, "tez boyish")
        dm_ai.calls.clear()
        session.clear()
        ai_handler._last_ask.clear()
        await say(dp, bot, f"{BOT} admin bilan gaplashmoqchiman")
        assert not dm_ai.calls and session.texts_to(USER) == [texts.SUPPORT_DECLINED["uz"]]


class TestPolicyPrompt:
    def test_prompt_covers_every_category_and_the_ask_first_rule(self):
        prompt = texts.SUPPORT_SYSTEM_PROMPT
        for category in (*support_policy.FORWARD_CATEGORIES, *support_policy.DECLINE_CATEGORIES):
            assert category in prompt, category
        assert "ALWAYS start by finding out WHAT the matter is" in prompt
        assert "music and concert advertising IS allowed" in prompt

    def test_prohibited_ads_include_the_agreed_list(self):
        joined = " ".join(support_policy.PROHIBITED_ADS)
        for word in ("gambling", "alcohol", "usury", "adult", "pork", "fortune", "fraud", "weapons", "tobacco",
                     "cryptocurrency", "insurance"):
            assert word in joined, word
        assert "music" not in joined and "concert" not in joined

    def test_tools_enums_match_the_policy(self):
        assert support.ESCALATE_TOOL["function"]["parameters"]["properties"]["category"]["enum"] == list(
            support_policy.FORWARD_CATEGORIES
        )
        assert support.DECLINE_TOOL["function"]["parameters"]["properties"]["category"]["enum"] == list(
            support_policy.DECLINE_CATEGORIES
        )
        assert [t["function"]["name"] for t in support.SUPPORT_TOOLS] == ["escalate_to_admin", "decline", "resolve"]


class TestLimit:
    @pytest.fixture(autouse=True)
    def _small_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(support, "SUPPORT_MAX_TURNS", 2)

    async def _to_limit(self, dp, bot, group_ai, dm_ai) -> None:
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Yana bir narsa?"
        await dm(dp, bot, "bir")  # 1-xabar: hali limit emas

    async def test_unsolved_conversation_is_declined_not_escalated(self, dp, bot, session, group_ai, dm_ai):
        await self._to_limit(dp, bot, group_ai, dm_ai)
        dm_ai.answer, dm_ai.tool_calls = "", []
        await dm(dp, bot, "ikki")
        assert not admin_notices(session)
        assert session.texts_to(USER)[-1] == texts.SUPPORT_DECLINED["uz"]
        assert (await get_support_chat(USER, "declined", 24))["category"] == "unclear"

    async def test_final_turn_offers_only_resolve_and_decline(self, dp, bot, session, group_ai, dm_ai):
        await self._to_limit(dp, bot, group_ai, dm_ai)
        await dm(dp, bot, "ikki")
        names = [t["function"]["name"] for t in dm_ai.tools[-1]]
        assert names == ["decline", "resolve"]
        assert texts.SUPPORT_LAST_TURN in [m["content"] for m in dm_ai.calls[-1]]

    async def test_escalate_at_the_limit_is_still_declined(self, dp, bot, session, group_ai, dm_ai):
        await self._to_limit(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Adminga yuboraman."
        dm_ai.tool_calls = [("escalate_to_admin", {"summary": "s", "category": "other"})]
        await dm(dp, bot, "ikki")
        assert not admin_notices(session) and await get_support_chat(USER, "declined", 24) is not None

    async def test_resolve_at_the_limit_closes_the_chat(self, dp, bot, session, group_ai, dm_ai):
        await self._to_limit(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Hal bo'ldi."
        dm_ai.tool_calls = [("resolve", {})]
        await dm(dp, bot, "ikki")
        assert await get_support_chat(USER, "resolved", 24) is not None and not admin_notices(session)

    async def test_ai_failure_at_the_limit_declines(self, dp, bot, session, group_ai, dm_ai):
        from utils.ai import AIError

        await self._to_limit(dp, bot, group_ai, dm_ai)
        dm_ai.error = AIError("xato")
        await dm(dp, bot, "ikki")
        assert not admin_notices(session) and await get_support_chat(USER, "declined", 24) is not None
