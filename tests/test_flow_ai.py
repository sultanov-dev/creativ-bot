"""handlers/ai.py: guruhdagi AI yordamchi (mention yoki AI javobiga reply)."""
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, SendMessage

import handlers.ai as ai_handler
import texts
from tests import telegram_fakes as tf
from tests.flow import feed
from utils.ai import AIError

G = tf.GROUP_ID
USER = 50
BOT = f"@{tf.BOT_USERNAME}"


@pytest.fixture
def fake_ai(monkeypatch):
    calls = []
    state = {"answer": "Javob matni", "error": None}

    async def ask(messages):
        calls.append(messages)
        if state["error"]:
            raise state["error"]
        return state["answer"]

    monkeypatch.setattr(ai_handler, "ask_ai", ask)
    ask.calls = calls
    ask.state = state
    return ask


async def say(dp, bot, text, *, user=USER, reply=None, mention_in_text=True):
    entities = [tf.mention(text)] if mention_in_text and BOT.lower() in text.lower() else None
    await feed(dp, bot, tf.group_message(user, text, reply_to=reply, entities=entities))


LOADING_TEXTS = set(texts.AI_LOADING.values())


def bot_replies(session):
    """Bot javoblari ("yuklanmoqda" xabarlarisiz)."""
    return [m for m in session.of(SendMessage) if m.chat_id == G and m.text not in LOADING_TEXTS]


def loading_messages(session):
    return [m for m in session.of(SendMessage) if m.chat_id == G and m.text in LOADING_TEXTS]


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

    async def test_plain_group_chatter_is_ignored(self, dp, bot, session, fake_ai):
        await say(dp, bot, "hammaga salom")
        assert not fake_ai.calls and not session.of(SendMessage)

    async def test_mention_of_another_user_is_ignored(self, dp, bot, session, fake_ai):
        raw = tf.group_message(USER, "@someone_else salom").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"]["entities"] = [{"type": "mention", "offset": 0, "length": 13}]
        await dp.feed_raw_update(bot, raw)
        assert not fake_ai.calls

    async def test_bot_name_without_mention_entity_is_ignored(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} salom", mention_in_text=False)
        assert not fake_ai.calls

    async def test_commands_never_reach_ai(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"/ask {BOT} nima")
        assert not fake_ai.calls

    async def test_private_chat_is_not_handled_by_ai(self, dp, bot, session, fake_ai):
        await feed(dp, bot, tf.private_message(USER, f"{BOT} salom"))
        assert not fake_ai.calls

    async def test_empty_question_gets_hint(self, dp, bot, session, fake_ai):
        await say(dp, bot, BOT)
        assert not fake_ai.calls
        assert "Savolingizni yozing" in bot_replies(session)[0].text and tf.BOT_USERNAME in bot_replies(session)[0].text

    async def test_too_long_question(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} " + "x" * 2001)
        assert not fake_ai.calls and bot_replies(session)[0].text == texts.AI_TOO_LONG["uz"]

    async def test_question_of_exactly_limit_is_accepted(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} " + "x" * 2000)
        assert len(fake_ai.calls) == 1


class TestCooldown:
    async def test_second_question_within_cooldown_is_refused(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} bir")
        await say(dp, bot, f"{BOT} ikki")
        assert len(fake_ai.calls) == 1
        assert bot_replies(session)[-1].text == texts.AI_COOLDOWN["uz"]

    async def test_other_users_are_not_blocked(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} bir", user=1)
        await say(dp, bot, f"{BOT} ikki", user=2)
        assert len(fake_ai.calls) == 2

    async def test_cooldown_expires(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} bir")
        ai_handler._last_ask[USER] -= ai_handler.COOLDOWN + 1
        await say(dp, bot, f"{BOT} ikki")
        assert len(fake_ai.calls) == 2

    async def test_empty_or_too_long_questions_do_not_consume_cooldown(self, dp, bot, session, fake_ai):
        await say(dp, bot, BOT)
        await say(dp, bot, f"{BOT} savol")
        assert len(fake_ai.calls) == 1

    async def test_cooldown_table_is_bounded(self, dp, bot, session, fake_ai, monkeypatch):
        monkeypatch.setattr(ai_handler, "_LAST_ASK_MAX", 5)
        for uid in range(100, 110):
            ai_handler._last_ask[uid] = -1000.0  # eskirgan yozuvlar
        await say(dp, bot, f"{BOT} savol")
        assert len(ai_handler._last_ask) <= 2


class TestConversation:
    async def test_replying_to_ai_answer_continues_without_mention(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} birinchi savol")
        answer = session.of(SendMessage)[-1]
        # bot javobi xabar sifatida eslab qolingan
        remembered_id = next(iter(ai_handler._ai_messages))[1]
        ai_handler._last_ask.clear()
        reply = tf.group_message_obj(tf.BOT_ID, "Javob matni", message_id=remembered_id)
        await say(dp, bot, "va yana?", reply=reply)
        assert len(fake_ai.calls) == 2
        history = fake_ai.calls[1]
        assert [m["role"] for m in history] == ["system", "assistant", "user"]
        assert history[1]["content"] == "Javob matni" and history[2]["content"] == "va yana?"

    async def test_reply_to_unrelated_message_is_ignored(self, dp, bot, session, fake_ai):
        await say(dp, bot, "oddiy javob", reply=tf.group_message_obj(7, "boshqa xabar", message_id=1))
        assert not fake_ai.calls

    async def test_reply_in_other_chat_with_same_message_id_is_not_ai_reply(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} savol")
        mid = next(iter(ai_handler._ai_messages))[1]
        reply = tf.group_message_obj(tf.BOT_ID, "x", chat_id=G - 1, message_id=mid)
        await feed(dp, bot, tf.group_message(USER, "salom", chat_id=G - 1, reply_to=reply))
        assert len(fake_ai.calls) == 1

    async def test_mention_replying_to_other_message_adds_it_as_context(self, dp, bot, session, fake_ai):
        quoted = tf.group_message_obj(7, "Bu xabar matni", message_id=2)
        await say(dp, bot, f"{BOT} tarjima qil", reply=quoted)
        content = fake_ai.calls[0][-1]["content"]
        assert content == "Xabar: Bu xabar matni\n\nSavol: tarjima qil"
        assert all(m["role"] != "assistant" for m in fake_ai.calls[0])

    async def test_long_quoted_context_is_truncated(self, dp, bot, session, fake_ai):
        quoted = tf.group_message_obj(7, "q" * 5000, message_id=2)
        await say(dp, bot, f"{BOT} xulosa", reply=quoted)
        assert len(fake_ai.calls[0][-1]["content"]) < 2100

    async def test_memory_of_ai_messages_is_bounded(self, dp, bot, session, fake_ai, monkeypatch):
        monkeypatch.setattr(ai_handler, "_AI_MESSAGES_MAX", 3)
        for i in range(10):
            ai_handler._last_ask.clear()
            await say(dp, bot, f"{BOT} savol {i}")
        assert len(ai_handler._ai_messages) <= 3


class TestAnswerDelivery:
    async def test_answer_is_sanitized(self, dp, bot, session, fake_ai):
        fake_ai.state["answer"] = "<b>qalin</b> <script>x</script> <a href=\"javascript:1\">link</a> - tire"
        await say(dp, bot, f"{BOT} savol")
        text = bot_replies(session)[0].text
        assert "<b>qalin</b>" in text and "<script>" not in text and "javascript" not in text and " - " not in text

    async def test_telegram_html_rejection_falls_back_to_plain_text(self, dp, bot, session, fake_ai):
        fake_ai.state["answer"] = "<b>qalin</b> matn"
        calls = []

        def reject_once(m):
            if m.text in LOADING_TEXTS:
                return None
            calls.append(m)
            return TelegramBadRequest(method=m, message="Bad Request: can't parse entities") if len(calls) == 1 else None

        session.errors[SendMessage] = reject_once
        await say(dp, bot, f"{BOT} savol")
        sent = [m for m in session.of(SendMessage) if m.text not in LOADING_TEXTS]
        assert len(sent) == 2 and sent[1].text == "qalin matn" and sent[1].parse_mode is None

    async def test_long_answer_is_split_into_at_most_two_messages(self, dp, bot, session, fake_ai):
        fake_ai.state["answer"] = "\n".join("satr " + "x" * 100 for _ in range(150))  # ~16000 belgi
        await say(dp, bot, f"{BOT} savol")
        parts = bot_replies(session)
        assert len(parts) == 2 and all(len(p.text) <= 4096 for p in parts)

    async def test_each_part_is_remembered_for_followups(self, dp, bot, session, fake_ai):
        fake_ai.state["answer"] = "\n".join("satr " + "x" * 100 for _ in range(150))
        await say(dp, bot, f"{BOT} savol")
        assert len(ai_handler._ai_messages) == 2

    async def test_html_expanding_answer_still_gets_delivered_as_plain_text(self, dp, bot, session, fake_ai):
        # 3000 ta "<" sanitize'dan keyin "&lt;" (12000 belgi) bo'ladi: Telegram rad etadi, oddiy matnga o'tiladi
        fake_ai.state["answer"] = "<" * 3000

        def too_long(m):
            return TelegramBadRequest(method=m, message="Bad Request: message is too long") if len(m.text) > 4096 else None

        session.errors[SendMessage] = too_long
        await say(dp, bot, f"{BOT} savol")
        sent = [m for m in session.of(SendMessage) if m.chat_id == G]
        assert sent and len(sent[-1].text) <= 4096

    async def test_unicode_and_emoji_answer(self, dp, bot, session, fake_ai):
        fake_ai.state["answer"] = "Салом 👋 ўзбек"
        await say(dp, bot, f"{BOT} savol")
        assert bot_replies(session)[0].text == "Салом 👋 ўзбек"


class TestFailures:
    async def test_ai_error_replies_generic_and_alerts_developer(self, dp, bot, session, fake_ai):
        fake_ai.state["error"] = AIError("AI API 500: boom")
        await say(dp, bot, f"{BOT} savol")
        assert bot_replies(session)[0].text == texts.AI_ERROR["uz"]
        dev = session.texts_to(tf.DEVELOPER_ID)
        assert len(dev) == 1 and "AIError" in dev[0]

    async def test_ai_error_text_never_reaches_the_group(self, dp, bot, session, fake_ai):
        fake_ai.state["error"] = AIError("secret internal detail test-token")
        await say(dp, bot, f"{BOT} savol")
        assert all("secret" not in m.text for m in bot_replies(session))

    async def test_failed_request_still_consumes_cooldown_so_outage_is_not_hammered(self, dp, bot, session, fake_ai):
        fake_ai.state["error"] = AIError("down")
        await say(dp, bot, f"{BOT} bir")
        await say(dp, bot, f"{BOT} ikki")
        assert len(fake_ai.calls) == 1

    async def test_repeated_identical_errors_alert_developer_once(self, dp, bot, session, fake_ai):
        fake_ai.state["error"] = AIError("down")
        for uid in (1, 2, 3):
            await say(dp, bot, f"{BOT} savol", user=uid)
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1

    async def test_unexpected_exception_is_contained(self, dp, bot, session, fake_ai):
        fake_ai.state["error"] = RuntimeError("bug")
        await say(dp, bot, f"{BOT} savol")  # dispatcher'dan chiqib ketmaydi
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1

    async def test_similar_username_is_not_mangled(self, dp, bot, session, fake_ai):
        text = f"{BOT} @{tf.BOT_USERNAME}_x ni qanday topaman?"
        await feed(dp, bot, tf.group_message(USER, text, entities=[tf.mention(text)]))
        assert f"@{tf.BOT_USERNAME}_x" in fake_ai.calls[0][-1]["content"]


class TestLoadingState:
    @pytest.mark.parametrize("question,lang", [
        ("bugun ob-havo qanday?", "uz"),
        ("Привет, как дела? Расскажи про Python", "ru"),
        ("What is the weather today?", "en"),
        ("Бугун об-ҳаво қандай?", "uz_cyr"),
        ("123 ???", "uz"),
    ])
    async def test_loading_text_matches_question_language(self, dp, bot, session, fake_ai, question, lang):
        await say(dp, bot, f"{BOT} {question}")
        loading = loading_messages(session)
        assert [m.text for m in loading] == [texts.AI_LOADING[lang]]
        assert loading[0].reply_parameters is not None  # savolga reply

    async def test_loading_is_shown_before_answer_and_removed_after(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT} salom")
        sent = [m for m in session.of(SendMessage) if m.chat_id == G]
        assert sent[0].text in LOADING_TEXTS and sent[1].text == "Javob matni"
        deleted = [m for m in session.of(DeleteMessage) if m.chat_id == G]
        assert len(deleted) == 1  # faqat "yuklanmoqda" xabari o'chdi, javob qoldi
        assert bot_replies(session)[0].text == "Javob matni"

    async def test_loading_removed_when_ai_fails(self, dp, bot, session, fake_ai):
        fake_ai.state["error"] = AIError("down")
        await say(dp, bot, f"{BOT} salom")
        assert len([m for m in session.of(DeleteMessage) if m.chat_id == G]) == 1
        assert bot_replies(session)[0].text == texts.AI_ERROR["uz"]

    async def test_failed_loading_message_does_not_break_the_answer(self, dp, bot, session, fake_ai):
        def only_loading_fails(m):
            return TelegramBadRequest(method=m, message="x") if m.text in LOADING_TEXTS else None

        session.errors[SendMessage] = only_loading_fails
        await say(dp, bot, f"{BOT} salom")
        assert bot_replies(session)[0].text == "Javob matni"
        assert not session.of(DeleteMessage)

    async def test_no_loading_for_rejected_questions(self, dp, bot, session, fake_ai):
        await say(dp, bot, f"{BOT}")
        assert not loading_messages(session)


class TestDetectLang:
    @pytest.mark.parametrize("text,lang", [
        ("salom, bu nima?", "uz"),
        ("o'zbekiston haqida ayt", "uz"),
        ("tell me how to write code", "en"),
        ("помоги мне с кодом", "ru"),
        ("менга ёрдам беринг", "uz_cyr"),
        ("", "uz"),
    ])
    def test_detect(self, text, lang):
        from utils.lang import detect_lang

        assert detect_lang(text) == lang


QUESTIONS = [
    ("uz", "bugun ob-havo qanday?"),
    ("uz_cyr", "Бугун об-ҳаво қандай?"),
    ("ru", "Привет, как дела? Расскажи про Python"),
    ("en", "What is the weather today?"),
]


class TestSystemMessagesInQuestionLanguage:
    @pytest.mark.parametrize("lang,question", QUESTIONS)
    async def test_error_message(self, dp, bot, session, fake_ai, lang, question):
        fake_ai.state["error"] = AIError("down")
        await say(dp, bot, f"{BOT} {question}")
        assert bot_replies(session)[0].text == texts.AI_ERROR[lang]

    @pytest.mark.parametrize("lang,question", QUESTIONS)
    async def test_cooldown_message(self, dp, bot, session, fake_ai, lang, question):
        await say(dp, bot, f"{BOT} {question}")
        await say(dp, bot, f"{BOT} {question}")
        assert bot_replies(session)[-1].text == texts.AI_COOLDOWN[lang]

    @pytest.mark.parametrize("lang,question", QUESTIONS)
    async def test_too_long_message(self, dp, bot, session, fake_ai, lang, question):
        padding = {"uz": "nima ", "uz_cyr": "қандай ", "ru": "как ", "en": "the "}[lang]
        await say(dp, bot, f"{BOT} {question} " + padding * 600)
        assert not fake_ai.calls
        expected = texts.AI_TOO_LONG[lang]
        assert bot_replies(session)[0].text == expected

    def test_every_language_has_every_message(self):
        for table in (texts.AI_LOADING, texts.AI_TOO_LONG, texts.AI_COOLDOWN, texts.AI_ERROR):
            assert set(table) == {"uz", "uz_cyr", "ru", "en"}
