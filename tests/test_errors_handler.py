"""handlers/errors.py: ushlanmagan xatolar (foydalanuvchi, dasturchi, takrorlanishni cheklash)."""
import pytest
from aiogram import Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery, SendMessage

import handlers.errors as errors
import texts
from callbacks import VoteCB
from tests import telegram_fakes as tf
from tests.flow import feed


@pytest.fixture
def boom_dp(db):
    """errors.router + har qanday xabar/callback'da `boom_dp.exc` ni tashlaydigan router."""
    boom = Router()
    holder = {"exc": RuntimeError("kutilmagan xato")}

    @boom.message()
    async def on_message(message):
        raise holder["exc"]

    @boom.callback_query()
    async def on_callback(call):
        raise holder["exc"]

    dispatcher = Dispatcher()
    dispatcher.include_routers(errors.router, boom)
    dispatcher.holder = holder
    yield dispatcher
    errors.router._parent_router = None


class TestBenign:
    @pytest.mark.parametrize("message", [
        "Bad Request: query is too old and response timeout expired",
        "Bad Request: message is not modified: specified new message content",
        "Forbidden: bot was blocked by the user",
        "Forbidden: user is deactivated",
        "Bad Request: message to edit not found",
    ])
    async def test_benign_errors_stay_quiet(self, boom_dp, bot, session, message):
        cls = TelegramForbiddenError if message.startswith("Forbidden") else TelegramBadRequest
        boom_dp.holder["exc"] = cls(method=None, message=message)
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        assert session.requests == []

    def test_is_benign_is_case_insensitive_and_type_aware(self):
        assert errors._is_benign(TelegramBadRequest(method=None, message="QUERY IS TOO OLD"))
        assert not errors._is_benign(RuntimeError("query is too old"))
        assert not errors._is_benign(TelegramBadRequest(method=None, message="Bad Request: chat not found"))


class TestReporting:
    async def test_private_message_error_tells_user_and_developer(self, boom_dp, bot, session):
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        assert session.texts_to(5) == [texts.ERROR_GENERIC]
        dev = session.texts_to(tf.DEVELOPER_ID)
        assert len(dev) == 1 and "RuntimeError" in dev[0] and "kutilmagan xato" in dev[0]
        assert "chat: 5" in dev[0] and "user: 5" in dev[0] and "update: message" in dev[0]

    async def test_group_error_does_not_spam_the_group(self, boom_dp, bot, session):
        await feed(boom_dp, bot, tf.group_message(5, "salom"))
        assert not session.sent_to(tf.GROUP_ID)
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1

    async def test_callback_error_is_shown_as_alert(self, boom_dp, bot, session):
        await feed(boom_dp, bot, tf.callback(5, VoteCB(vote="yes", app_id=1).pack()))
        alert = session.of(AnswerCallbackQuery)[0]
        assert alert.text == texts.ERROR_GENERIC and alert.show_alert is True
        assert "update: callback_query" in session.texts_to(tf.DEVELOPER_ID)[0]

    async def test_developer_alert_is_html_escaped_and_truncated(self, boom_dp, bot, session):
        boom_dp.holder["exc"] = RuntimeError("<b>" + "x" * 1000)
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        text = session.texts_to(tf.DEVELOPER_ID)[0]
        assert "<b>xxx" not in text and "&lt;b&gt;" in text and len(text) < 600

    async def test_same_error_is_reported_once_per_cooldown(self, boom_dp, bot, session):
        for _ in range(5):
            await feed(boom_dp, bot, tf.private_message(5, "salom"))
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1
        assert len(session.texts_to(5)) == 5  # foydalanuvchi har safar xabar oladi

    async def test_different_errors_are_each_reported(self, boom_dp, bot, session):
        await feed(boom_dp, bot, tf.private_message(5, "a"))
        boom_dp.holder["exc"] = ValueError("boshqa")
        await feed(boom_dp, bot, tf.private_message(5, "b"))
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 2

    async def test_cooldown_expiry_allows_a_new_alert(self, boom_dp, bot, session):
        await feed(boom_dp, bot, tf.private_message(5, "a"))
        for key in errors._last_alert:
            errors._last_alert[key] -= errors.ALERT_COOLDOWN + 1
        await feed(boom_dp, bot, tf.private_message(5, "b"))
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 2

    async def test_stale_alert_entries_are_purged_once_table_is_full(self, boom_dp, bot, session, monkeypatch):
        monkeypatch.setattr(errors, "_LAST_ALERT_MAX", 3)
        for i in range(5):
            errors._last_alert[f"eski{i}"] = -10_000.0  # cooldown'i o'tgan
        await feed(boom_dp, bot, tf.private_message(5, "x"))
        assert not any(k.startswith("eski") for k in errors._last_alert)
        assert len(errors._last_alert) == 1

    async def test_no_developers_configured(self, boom_dp, bot, session, monkeypatch):
        monkeypatch.setattr(errors, "DEVELOPER_IDS", [])
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        assert session.texts_to(5) == [texts.ERROR_GENERIC]

    async def test_undeliverable_developer_alert_is_swallowed(self, boom_dp, bot, session):
        session.errors[SendMessage] = lambda m: TelegramForbiddenError(method=m, message="Forbidden: blocked") \
            if m.chat_id == tf.DEVELOPER_ID else None
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        assert session.texts_to(5) == [texts.ERROR_GENERIC]

    async def test_error_while_notifying_user_does_not_hide_developer_alert(self, boom_dp, bot, session):
        session.errors[SendMessage] = lambda m: TelegramForbiddenError(method=m, message="Forbidden: blocked") \
            if m.chat_id == 5 else None
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1

    async def test_error_is_logged_with_traceback(self, boom_dp, bot, session, caplog):
        await feed(boom_dp, bot, tf.private_message(5, "salom"))
        rec = next(r for r in caplog.records if "Ushlanmagan xatolik" in r.message)
        assert rec.exc_info is not None
