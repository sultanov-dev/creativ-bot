"""handlers/support.py: guruhda contact_admin chaqirilganda lichkaga yozish va guruhdagi qisqa xabar."""
import pytest
from aiogram.methods import SendChatAction, SendMessage

import handlers.ai as ai_handler
import handlers.support as support
import texts
from config import ADMIN_IDS
from database import create_support_chat, get_support_chat, set_support_status
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


class TestUserMessageCleanup:
    """\"Lichkaga yozdim\" xabari va foydalanuvchi xabari qoladi; \"/start bosing\" xabari esa foydalanuvchi xabari bilan birga o'chadi."""

    async def _pending(self, message_id: int) -> bool:
        import database

        rows = await database.get_pending_deletes()
        return any(r["chat_id"] == tf.GROUP_ID and r["message_id"] == message_id for r in rows)

    async def _pending_any(self) -> bool:
        import database

        return bool(await database.get_pending_deletes())

    async def _ask(self, dp, bot, text: str, message_id: int) -> None:
        entities = [tf.mention(text)]
        await feed(dp, bot, tf.group_message(USER, text, entities=entities, message_id=message_id))

    async def test_dm_notice_and_user_message_stay(self, dp, bot, session, group_ai, dm_ai):
        await self._ask(dp, bot, f"{BOT} admin bilan gaplashmoqchiman", 4242)
        assert not await self._pending(4242)
        assert not await self._pending_any()

    async def test_user_message_is_deleted_after_start_first_notice(self, dp, bot, session, group_ai, dm_ai):
        session.errors[SendChatAction] = tf.forbidden()
        await self._ask(dp, bot, f"{BOT} admin bilan gaplashmoqchiman", 4243)
        assert await self._pending(4243)

    async def test_ordinary_ai_question_is_not_deleted(self, dp, bot, session, dm_ai, monkeypatch):
        fake = FakeAsk()
        monkeypatch.setattr(ai_handler, "ask_ai_tools", fake)
        await self._ask(dp, bot, f"{BOT} salom", 4244)
        assert not await self._pending(4244)


# ---- gatekeeper: adminga faqat toza va haq masalalar boradi

class FakeSay:
    """handlers.support.ask_ai o'rniga: qaror bajarilgach AI yozadigan yakuniy javob."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.answer = "AI yakuniy javob"
        self.error: Exception | None = None

    async def __call__(self, messages: list[dict[str, str]], **kw) -> str:
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.answer

    @property
    def outcome(self) -> str:
        """Oxirgi chaqiruvda AI'ga aytilgan natija."""
        return self.calls[-1][-1]["content"]


@pytest.fixture(autouse=True)
def say_ai(monkeypatch: pytest.MonkeyPatch) -> FakeSay:
    fake = FakeSay()
    monkeypatch.setattr(support, "ask_ai", fake)
    return fake


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


async def close_chat_by_abuse(dp, bot, dm_ai) -> None:
    """Suhbatni yopishning bir yo'li: ikki marta odobsiz xabar (adminga bormaydi, AI chaqirilmaydi)."""
    await dm(dp, bot, "BADWORD birinchi")
    await dm(dp, bot, "BADWORD ikkinchi")


def admin_notices(session) -> list[str]:
    return [t for a in ADMIN_IDS for t in session.texts_to(a)]


class TestGatekeeper:
    async def test_escalation_reaches_admins_without_category_label(self, dp, bot, session, group_ai, dm_ai, say_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "AI yozgan matn"
        dm_ai.tool_calls = [("escalate_to_admin", {"summary": "Tolov qaytmadi", "category": "payment"})]
        await dm(dp, bot, "Pulim qaytmadi")
        assert "AI yozgan matn" not in session.texts_to(USER)  # tool bilan birga yozilgan matn yuborilmaydi
        assert session.texts_to(USER)[-1] == say_ai.answer  # yakuniy javobni AI natijadan xabardor holda yozadi
        assert say_ai.outcome == texts.SUPPORT_OUTCOME_ESCALATED
        notices = admin_notices(session)
        assert len(notices) == len(ADMIN_IDS) and "Tolov qaytmadi" in notices[0]
        assert "payment" not in notices[0] and "ategoriya" not in notices[0]
        chat = await get_support_chat(USER, "escalated", 24)
        assert chat is not None and chat["category"] == "payment"

    async def test_problem_solved_by_the_ai_never_reaches_the_admins(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Mana yechim. Yana savol bormi?"
        dm_ai.tool_calls = []
        await dm(dp, bot, "Botga qanday qo'shilaman?")
        dm_ai.answer = "Marhamat!"
        dm_ai.tool_calls = [("resolve", {})]
        await dm(dp, bot, "Rahmat, tushundim")
        assert not admin_notices(session)
        chat = await get_support_chat(USER, "resolved", 24)
        assert chat is not None and await get_support_chat(USER, "escalated", 24) is None

    async def test_decline_keeps_the_matter_from_admins_and_logs_the_category(
        self, dp, bot, session, group_ai, dm_ai, say_ai
    ):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Adminga yuboraman."  # AI decline bilan zid matn yozsa ham foydalanuvchiga bormaydi
        dm_ai.tool_calls = [("decline", {"category": "prohibited_ad"})]
        await dm(dp, bot, "Kazino reklamasini bermoqchiman")
        assert not admin_notices(session)
        user_texts = session.texts_to(USER)
        assert "Adminga yuboraman." not in user_texts and user_texts[-1] == say_ai.answer
        assert say_ai.outcome == texts.SUPPORT_OUTCOME_DECLINED and "NOT passed" in say_ai.outcome
        chat = await get_support_chat(USER, "active", 24)  # suhbat tugamaydi
        assert chat is not None and chat["category"] == "prohibited_ad"

    async def test_conversation_continues_after_a_decline(self, dp, bot, session, group_ai, dm_ai, say_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer, dm_ai.tool_calls = "", [("decline", {"category": "no_purpose"})]
        await dm(dp, bot, "shaxsiy ishim bor")
        dm_ai.answer, dm_ai.tool_calls = "Qanday shaxsiy masala? Aniqroq ayting.", []
        session.clear()
        await dm(dp, bot, "shaxsiy masala bor")
        assert session.texts_to(USER) == ["Qanday shaxsiy masala? Aniqroq ayting."]  # tayyor rad matni emas, AI o'zi yozadi
        assert dm_ai.calls[-1][-1]["content"] == "shaxsiy masala bor" or any(
            m["content"] == "shaxsiy masala bor" for m in dm_ai.calls[-1]
        )

    async def test_ai_failure_falls_back_to_the_category_text(self, dp, bot, session, group_ai, dm_ai, say_ai):
        from utils.ai import AIError

        await start_chat(dp, bot, group_ai, dm_ai)
        say_ai.error = AIError("xato")
        dm_ai.answer, dm_ai.tool_calls = "", [("decline", {"category": "no_purpose"})]
        await dm(dp, bot, "admin kerak")
        assert session.texts_to(USER)[-1] == texts.SUPPORT_DECLINED_BY_CATEGORY["no_purpose"]["uz"]
        assert not admin_notices(session)

    async def test_other_categories_fall_back_to_the_generic_refusal(self, dp, bot, session, group_ai, dm_ai, say_ai):
        from utils.ai import AIError

        await start_chat(dp, bot, group_ai, dm_ai)
        say_ai.error = AIError("xato")
        dm_ai.answer, dm_ai.tool_calls = "", [("decline", {"category": "spam"})]
        await dm(dp, bot, "arzon telefon sotaman")
        assert session.texts_to(USER)[-1] == texts.SUPPORT_DECLINED["uz"]

    async def test_user_is_told_it_was_passed_before_the_admins_receive_it(self, dp, bot, session, group_ai, dm_ai, say_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer, dm_ai.tool_calls = "", [("escalate_to_admin", {"summary": "Tolov qaytmadi", "category": "payment"})]
        await dm(dp, bot, "Pulim qaytmadi")
        order = [m.chat_id for m in session.of(SendMessage) if m.chat_id == USER or m.chat_id in ADMIN_IDS]
        assert order[-3:] == [USER, *ADMIN_IDS]  # avval foydalanuvchiga "yetkazildi", keyin adminlarga
        assert say_ai.outcome == texts.SUPPORT_OUTCOME_ESCALATED

    async def test_unreachable_admins_reopen_the_chat_and_correct_the_message(self, dp, bot, session, group_ai, dm_ai, say_ai):
        session.errors[SendMessage] = lambda m: tf.forbidden() if m.chat_id in ADMIN_IDS else None
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer, dm_ai.tool_calls = "", [("escalate_to_admin", {"summary": "s", "category": "other"})]
        await dm(dp, bot, "masala")
        user_texts = session.texts_to(USER)
        assert user_texts[-2:] == [say_ai.answer, texts.SUPPORT_ADMIN_UNAVAILABLE["uz"]]  # yetkazildi, keyin tuzatish
        assert await get_support_chat(USER, "active", 24) is not None  # suhbat qayta ochiq

    async def test_unknown_categories_fall_back_safely(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = ""
        dm_ai.tool_calls = [("decline", {"category": "xyz"}), ("escalate_to_admin", {"summary": "s", "category": "other"})]
        await dm(dp, bot, "gap")
        assert not admin_notices(session)  # ikkalasi bo'lsa, xavfsizi: rad
        assert (await get_support_chat(USER, "active", 24))["category"] == "unclear"

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

    async def test_daily_escalation_limit(self, dp, bot, session, group_ai, dm_ai, say_ai):
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
        assert say_ai.outcome == texts.SUPPORT_OUTCOME_LIMIT and session.texts_to(USER)[-1] == say_ai.answer

    async def test_recently_declined_user_gets_a_short_refusal_without_ai(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        await close_chat_by_abuse(dp, bot, dm_ai)
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
        assert "decline does NOT end the conversation" in prompt  # rad etilgach ham suhbat davom etadi
        assert "refer to what the user wrote in the group" in prompt

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


class TestIdleReplies:
    """Suhbat yopilgan yoki ochilmagan: bot jim turmaydi."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        support._last_idle.clear()
        yield
        support._last_idle.clear()

    async def test_user_without_a_chat_gets_the_how_to_hint(self, dp, bot, session):
        await dm(dp, bot, "salom")
        assert session.texts_to(USER) == [texts.SUPPORT_IDLE["uz"].format(username=tf.BOT_USERNAME)]

    async def test_declined_user_keeps_getting_the_refusal_not_silence(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        await close_chat_by_abuse(dp, bot, dm_ai)
        session.clear()
        await dm(dp, bot, "shaxsiy ishim bor")
        assert session.texts_to(USER) == [texts.SUPPORT_DECLINED["uz"]]
        assert not admin_notices(session)

    async def test_replies_are_throttled_to_one_per_minute(self, dp, bot, session):
        await dm(dp, bot, "salom")
        await dm(dp, bot, "aloo")
        assert len(session.texts_to(USER)) == 1
        support._last_idle[USER] -= support.WAIT_NOTICE_INTERVAL + 1
        await dm(dp, bot, "aloo")
        assert len(session.texts_to(USER)) == 2

    async def test_resolved_chat_user_gets_the_hint(self, dp, bot, session, group_ai, dm_ai):
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer, dm_ai.tool_calls = "Marhamat!", [("resolve", {})]
        await dm(dp, bot, "rahmat")
        session.clear()
        await dm(dp, bot, "yana savol bor")
        assert session.texts_to(USER) == [texts.SUPPORT_IDLE["uz"].format(username=tf.BOT_USERNAME)]

    async def test_bot_admins_are_not_answered(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(ADMIN_IDS[0], "salom"))
        assert not session.texts_to(ADMIN_IDS[0])


class TestStaleDeclined:
    """Eski versiyada rad etish suhbatni yopardi: bazada qolgan bunday yozuvlar foydalanuvchini 24 soat to'smasin."""

    async def _old_declined(self, category: str) -> None:
        chat_id = await create_support_chat(USER, tf.GROUP_ID, "G", "U50", None, "active")
        assert await set_support_status(chat_id, "active", "declined", category)

    @pytest.mark.parametrize("category", ["no_purpose", "prohibited_ad", "unclear", "indecent"])
    async def test_old_decline_does_not_block_a_new_conversation(self, dp, bot, session, group_ai, dm_ai, category):
        await self._old_declined(category)
        await say(dp, bot, f"{BOT} admin bilan gaplashmoqchiman")
        assert dm_ai.calls and session.texts_to(USER) == ["Salom! Nima bo'ldi?"]  # tayyor rad matni emas, AI yozadi
        assert [m.text for m in bot_replies(session)] == [texts.SUPPORT_DM_SENT["uz"]]

    async def test_old_decline_does_not_make_the_idle_reply_a_refusal(self, dp, bot, session):
        support._last_idle.clear()
        await self._old_declined("no_purpose")
        await dm(dp, bot, "salom")
        assert session.texts_to(USER) == [texts.SUPPORT_IDLE["uz"].format(username=tf.BOT_USERNAME)]

    @pytest.mark.parametrize("category", ["abuse", "limit"])
    async def test_abuse_and_limit_closures_still_block(self, dp, bot, session, group_ai, dm_ai, category):
        await self._old_declined(category)
        await say(dp, bot, f"{BOT} admin bilan gaplashmoqchiman")
        assert not dm_ai.calls and session.texts_to(USER) == [texts.SUPPORT_DECLINED["uz"]]

    async def test_idle_reply_interval_is_short(self):
        assert support.IDLE_NOTICE_INTERVAL <= 10


class TestLimit:
    @pytest.fixture(autouse=True)
    def _small_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(support, "SUPPORT_MAX_TURNS", 2)

    async def _to_limit(self, dp, bot, group_ai, dm_ai) -> None:
        await start_chat(dp, bot, group_ai, dm_ai)
        dm_ai.answer = "Yana bir narsa?"
        await dm(dp, bot, "bir")  # 1-xabar: hali limit emas

    async def test_unsolved_conversation_is_declined_not_escalated(self, dp, bot, session, group_ai, dm_ai, say_ai):
        await self._to_limit(dp, bot, group_ai, dm_ai)
        dm_ai.answer, dm_ai.tool_calls = "", []
        await dm(dp, bot, "ikki")
        assert not admin_notices(session)
        assert say_ai.outcome == texts.SUPPORT_OUTCOME_CLOSED and session.texts_to(USER)[-1] == say_ai.answer
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
