"""handlers/ai.py: guruhdagi AI yordamchi (mention yoki AI javobiga reply)."""
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, SendMessage
from aiogram.methods.base import TelegramMethod

import handlers.ai as ai_handler
import texts
from tests import telegram_fakes as tf
from tests.flow import feed
from utils.ai import AIError
from utils.lang import detect_lang

G = tf.GROUP_ID
USER = 50
BOT = f"@{tf.BOT_USERNAME}"
LOADING_TEXTS = set(texts.AI_LOADING.values())
LONG_ANSWER = "\n".join("satr " + "x" * 100 for _ in range(150))  # ~16000 belgi


class FakeAsk:
    """handlers.ai.ask_ai o'rniga: chaqiruvlarni yozadi, javob/xatoni test belgilaydi."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.answer = "Javob matni"
        self.error: Exception | None = None

    async def __call__(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if self.error:
            raise self.error
        return self.answer


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> FakeAsk:
    fake = FakeAsk()
    monkeypatch.setattr(ai_handler, "ask_ai", fake)
    return fake


async def say(dp, bot, text: str, *, user: int = USER, reply=None, mention_in_text: bool = True) -> None:
    entities = [tf.mention(text)] if mention_in_text and BOT.lower() in text.lower() else None
    await feed(dp, bot, tf.group_message(user, text, reply_to=reply, entities=entities))


def bot_replies(session) -> list[SendMessage]:
    """Bot javoblari ("yuklanmoqda" xabarlarisiz)."""
    return [m for m in session.of(SendMessage) if m.chat_id == G and m.text not in LOADING_TEXTS]


def loading_messages(session) -> list[SendMessage]:
    return [m for m in session.of(SendMessage) if m.chat_id == G and m.text in LOADING_TEXTS]


def deleted_in_group(session) -> list[DeleteMessage]:
    return [m for m in session.of(DeleteMessage) if m.chat_id == G]


def bad_request(m: TelegramMethod, message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=m, message=f"Bad Request: {message}")


class TestTriggering:
    async def test_mention_triggers_ai(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} bugun ob-havo qanday?")
        assert len(fake_ai.calls) == 1
        messages = fake_ai.calls[0]
        assert messages[0] == {"role": "system", "content": texts.AI_SYSTEM_PROMPT}
        assert messages[-1] == {"role": "user", "content": "bugun ob-havo qanday?"}
        assert bot_replies(session)[0].text == "Javob matni"
        assert bot_replies(session)[0].reply_parameters is not None

    async def test_mention_is_case_insensitive_and_can_be_anywhere(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"salom {BOT.upper()} yordam bering")
        assert fake_ai.calls[0][-1]["content"] == "salom  yordam bering"

    async def test_similar_username_is_not_mangled(self, dp, bot, session, fake_ai):
        text = f"{BOT} @{tf.BOT_USERNAME}_x ni qanday topaman?"
        await feed(dp, bot, tf.group_message(USER, text, entities=[tf.mention(text)]))
        assert f"@{tf.BOT_USERNAME}_x" in fake_ai.calls[0][-1]["content"]

    async def test_non_triggering_messages_are_ignored(self, dp, bot, session, fake_ai):
        await say(dp, bot, "hammaga salom")
        await say(dp, bot, f"{BOT} salom", mention_in_text=False)  # mention entity'siz
        await say(dp, bot, f"/ask {BOT} nima")
        await feed(dp, bot, tf.private_message(USER, f"{BOT} salom"))
        raw = tf.group_message(USER, "@someone_else salom").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"]["entities"] = [{"type": "mention", "offset": 0, "length": 13}]
        await dp.feed_raw_update(bot, raw)
        assert not fake_ai.calls and not session.of(SendMessage)

    async def test_empty_question_gets_hint(self, dp, bot, session, fake_ai):
        await say(dp, bot, BOT)
        assert not fake_ai.calls and not loading_messages(session)
        text = bot_replies(session)[0].text
        assert text is not None and "Savolingizni yozing" in text and tf.BOT_USERNAME in text

    async def test_question_length_limit(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} " + "x" * 2001)
        assert not fake_ai.calls and bot_replies(session)[0].text == texts.AI_TOO_LONG["uz"]
        await say(dp, bot, f"{BOT} " + "x" * 2000)  # rad etilgan savol cooldown'ni sarflamaydi
        assert len(fake_ai.calls) == 1


class TestCooldown:
    async def test_per_user_cooldown_and_expiry(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} bir", user=1)
        await say(dp, bot, f"{BOT} ikki", user=1)
        assert len(fake_ai.calls) == 1 and bot_replies(session)[-1].text == texts.AI_COOLDOWN["uz"]
        await say(dp, bot, f"{BOT} uch", user=2)  # boshqa foydalanuvchi bloklanmaydi
        assert len(fake_ai.calls) == 2
        ai_handler._last_ask[1] -= ai_handler.COOLDOWN + 1
        await say(dp, bot, f"{BOT} to'rt", user=1)
        assert len(fake_ai.calls) == 3

    async def test_cooldown_table_is_bounded(self, dp, bot, session, fake_ai, monkeypatch):
        monkeypatch.setattr(ai_handler, "_LAST_ASK_MAX", 5)
        for uid in range(100, 110):
            ai_handler._last_ask[uid] = -1000.0  # eskirgan yozuvlar
        await say(dp, bot, f"{BOT} savol")
        assert len(ai_handler._last_ask) <= 2


class TestConversation:
    async def test_replying_to_ai_answer_continues_without_mention(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} birinchi savol")
        remembered_id = next(iter(ai_handler._ai_messages))[1]  # bot javobi eslab qolingan
        ai_handler._last_ask.clear()
        reply = tf.group_message_obj(tf.BOT_ID, "Javob matni", message_id=remembered_id)
        await say(dp, bot, "va yana?", reply=reply)
        assert len(fake_ai.calls) == 2
        history = fake_ai.calls[1]
        assert [m["role"] for m in history] == ["system", "assistant", "user"]
        assert history[1]["content"] == "Javob matni" and history[2]["content"] == "va yana?"

    async def test_unrelated_replies_are_not_ai_replies(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} savol")
        mid = next(iter(ai_handler._ai_messages))[1]
        other_chat = tf.group_message_obj(tf.BOT_ID, "x", chat_id=G - 1, message_id=mid)  # boshqa chat, o'sha id
        await feed(dp, bot, tf.group_message(USER, "salom", chat_id=G - 1, reply_to=other_chat))
        await say(dp, bot, "oddiy javob", reply=tf.group_message_obj(7, "boshqa xabar", message_id=1))
        assert len(fake_ai.calls) == 1

    async def test_mention_replying_to_other_message_adds_truncated_context(self, dp, bot, session, fake_ai):
        quoted = tf.group_message_obj(7, "Bu xabar matni", message_id=2)
        await say(dp, bot, f"{BOT} tarjima qil", reply=quoted)
        assert fake_ai.calls[0][-1]["content"] == "Xabar: Bu xabar matni\n\nSavol: tarjima qil"
        assert all(m["role"] != "assistant" for m in fake_ai.calls[0])
        ai_handler._last_ask.clear()
        await say(dp, bot, f"{BOT} xulosa", reply=tf.group_message_obj(7, "q" * 5000, message_id=3))
        assert len(fake_ai.calls[1][-1]["content"]) < 2100

    async def test_memory_of_ai_messages_is_bounded(self, dp, bot, session, fake_ai, monkeypatch):
        monkeypatch.setattr(ai_handler, "_AI_MESSAGES_MAX", 3)
        for i in range(10):
            ai_handler._last_ask.clear()
            await say(dp, bot, f"{BOT} savol {i}")
        assert len(ai_handler._ai_messages) <= 3


class TestAnswerDelivery:
    async def test_answer_is_sanitized(self, dp, bot, session, fake_ai):
        fake_ai.answer = "<b>qalin</b> <script>x</script> <a href=\"javascript:1\">link</a> - tire Салом 👋"
        await say(dp, bot, f"{BOT} savol")
        text = bot_replies(session)[0].text
        assert text is not None
        assert "<b>qalin</b>" in text and "<script>" not in text and "javascript" not in text and " - " not in text
        assert "Салом 👋" in text

    async def test_telegram_html_rejection_falls_back_to_plain_text(self, dp, bot, session, fake_ai):
        fake_ai.answer = "<b>qalin</b> matn"
        attempts: list[SendMessage] = []

        def reject_once(m: SendMessage) -> TelegramBadRequest | None:
            if m.text in LOADING_TEXTS:
                return None
            attempts.append(m)
            return bad_request(m, "can't parse entities") if len(attempts) == 1 else None

        session.errors[SendMessage] = reject_once
        await say(dp, bot, f"{BOT} savol")
        sent = bot_replies(session)
        assert len(sent) == 2 and sent[1].text == "qalin matn" and sent[1].parse_mode is None

    async def test_long_answer_is_split_into_two_remembered_messages(self, dp, bot, session, fake_ai):
        fake_ai.answer = LONG_ANSWER
        await say(dp, bot, f"{BOT} savol")
        parts = bot_replies(session)
        assert len(parts) == 2 and all(p.text is not None and len(p.text) <= 4096 for p in parts)
        assert len(ai_handler._ai_messages) == 2  # har bir qism keyingi savol uchun eslab qolinadi

    async def test_html_expanding_answer_still_gets_delivered_as_plain_text(self, dp, bot, session, fake_ai):
        # 3000 ta "<" sanitize'dan keyin "&lt;" (12000 belgi) bo'ladi: Telegram rad etadi, oddiy matnga o'tiladi
        fake_ai.answer = "<" * 3000

        def too_long(m: SendMessage) -> TelegramBadRequest | None:
            return bad_request(m, "message is too long") if m.text is not None and len(m.text) > 4096 else None

        session.errors[SendMessage] = too_long
        await say(dp, bot, f"{BOT} savol")
        sent = bot_replies(session)
        assert sent and (sent[-1].text or "") and len(sent[-1].text or "") <= 4096


class TestFailures:
    async def test_ai_error_replies_generic_and_alerts_developer(self, dp, bot, session, fake_ai):
        fake_ai.error = AIError("AI API 500: secret internal detail test-token")
        await say(dp, bot, f"{BOT} savol")
        assert [m.text for m in bot_replies(session)] == [texts.AI_ERROR["uz"]]  # ichki matn guruhga chiqmaydi
        dev = session.texts_to(tf.DEVELOPER_ID)
        assert len(dev) == 1 and "AIError" in dev[0]

    async def test_failed_request_still_consumes_cooldown(self, dp, bot, session, fake_ai):
        fake_ai.error = AIError("down")  # uzilish paytida API'ga bosim o'tkazilmaydi
        await say(dp, bot, f"{BOT} bir")
        await say(dp, bot, f"{BOT} ikki")
        assert len(fake_ai.calls) == 1

    async def test_repeated_identical_errors_alert_developer_once(self, dp, bot, session, fake_ai):
        fake_ai.error = AIError("down")
        for uid in (1, 2, 3):
            await say(dp, bot, f"{BOT} savol", user=uid)
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1

    async def test_unexpected_exception_is_contained(self, dp, bot, session, fake_ai):
        fake_ai.error = RuntimeError("bug")
        await say(dp, bot, f"{BOT} savol")  # dispatcher'dan chiqib ketmaydi
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1


class TestLoadingState:
    async def test_loading_is_shown_before_answer_and_removed_after(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} salom")
        sent = [m for m in session.of(SendMessage) if m.chat_id == G]
        assert sent[0].text in LOADING_TEXTS and sent[0].reply_parameters is not None
        assert sent[1].text == "Javob matni"
        assert len(deleted_in_group(session)) == 1  # faqat "yuklanmoqda" o'chdi, javob qoldi

    async def test_loading_removed_when_ai_fails(self, dp, bot, session, fake_ai):
        fake_ai.error = AIError("down")
        await say(dp, bot, f"{BOT} salom")
        assert len(deleted_in_group(session)) == 1
        assert bot_replies(session)[0].text == texts.AI_ERROR["uz"]

    async def test_failed_loading_message_does_not_break_the_answer(self, dp, bot, session, fake_ai):
        def only_loading_fails(m: SendMessage) -> TelegramBadRequest | None:
            return bad_request(m, "x") if m.text in LOADING_TEXTS else None

        session.errors[SendMessage] = only_loading_fails
        await say(dp, bot, f"{BOT} salom")
        assert bot_replies(session)[0].text == "Javob matni"
        assert not session.of(DeleteMessage)


QUESTIONS = [
    ("uz", "bugun ob-havo qanday?", "nima "),
    ("uz_cyr", "Бугун об-ҳаво қандай?", "қандай "),
    ("ru", "Привет, как дела? Расскажи про Python", "как "),
    ("en", "What is the weather today?", "the "),
]


class TestSystemMessagesInQuestionLanguage:
    @pytest.mark.parametrize("lang,question,padding", QUESTIONS)
    async def test_loading_cooldown_error_and_too_long(self, dp, bot, session, fake_ai, lang, question, padding):
        await say(dp, bot, f"{BOT} {question}")
        assert [m.text for m in loading_messages(session)] == [texts.AI_LOADING[lang]]
        await say(dp, bot, f"{BOT} {question}")
        assert bot_replies(session)[-1].text == texts.AI_COOLDOWN[lang]
        ai_handler._last_ask.clear()
        await say(dp, bot, f"{BOT} {question} " + padding * 600)
        assert len(fake_ai.calls) == 1 and bot_replies(session)[-1].text == texts.AI_TOO_LONG[lang]
        fake_ai.error = AIError("down")
        await say(dp, bot, f"{BOT} {question}")
        assert bot_replies(session)[-1].text == texts.AI_ERROR[lang]

    @pytest.mark.parametrize("text,lang", [
        ("salom, bu nima?", "uz"),
        ("o'zbekiston haqida ayt", "uz"),
        ("tell me how to write code", "en"),
        ("помоги мне с кодом", "ru"),
        ("менга ёрдам беринг", "uz_cyr"),
        ("123 ???", "uz"),
        ("", "uz"),
    ])
    def test_detect_lang(self, text, lang):
        assert detect_lang(text) == lang

    def test_every_language_has_every_message(self):
        for table in (texts.AI_LOADING, texts.AI_TOO_LONG, texts.AI_COOLDOWN, texts.AI_ERROR):
            assert set(table) == {"uz", "uz_cyr", "ru", "en"}
