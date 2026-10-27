"""handlers/support.py: guruhda contact_admin chaqirilganda lichkaga yozish va guruhdagi qisqa xabar."""
import pytest
from aiogram.methods import SendChatAction, SendMessage

import handlers.ai as ai_handler
import handlers.support as support
import texts
from database import get_support_chat
from tests import telegram_fakes as tf
from tests.test_flow_ai import BOT, USER, FakeAsk, bot_replies, say


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
