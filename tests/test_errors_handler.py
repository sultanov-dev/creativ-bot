"""handlers/errors.py: ushlanmagan xatolar (foydalanuvchi, dasturchi, takrorlanishni cheklash)."""
from dataclasses import dataclass
from typing import Iterator

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.methods import AnswerCallbackQuery, GetMe, SendMessage
from aiogram.types import CallbackQuery, Message

import handlers.errors as errors
import texts
from callbacks import VoteCB
from tests import telegram_fakes as tf
from tests.flow import feed

U = 5


@dataclass
class Boom:  # errors.router + har qanday xabar/callback'da `exc` ni tashlaydigan router
    dp: Dispatcher
    exc: Exception


@pytest.fixture
def boom(db) -> Iterator[Boom]:
    state = Boom(Dispatcher(), RuntimeError("kutilmagan xato"))
    router = Router()

    @router.message()
    async def on_message(message: Message) -> None:
        raise state.exc

    @router.callback_query()
    async def on_callback(call: CallbackQuery) -> None:
        raise state.exc

    state.dp.include_routers(errors.router, router)
    yield state
    errors.router._parent_router = None


async def fire(boom: Boom, bot: Bot, text: str = "salom") -> None:
    await feed(boom.dp, bot, tf.private_message(U, text))


class TestBenign:
    async def test_benign_errors_stay_quiet(self, boom, bot, session):
        for cls, message in [
            (TelegramBadRequest, "Bad Request: query is too old and response timeout expired"),
            (TelegramBadRequest, "Bad Request: message is not modified: specified new message content"),
            (TelegramForbiddenError, "Forbidden: bot was blocked by the user"),
            (TelegramForbiddenError, "Forbidden: user is deactivated"),
            (TelegramBadRequest, "Bad Request: message to edit not found"),
        ]:
            boom.exc = cls(method=GetMe(), message=message)
            await fire(boom, bot)
            assert session.requests == [], message

    def test_is_benign_is_case_insensitive_and_type_aware(self):
        assert errors._is_benign(TelegramBadRequest(method=GetMe(), message="QUERY IS TOO OLD"))
        assert not errors._is_benign(RuntimeError("query is too old"))
        assert not errors._is_benign(tf.bad_request("Bad Request: chat not found"))


class TestReporting:
    async def test_private_message_error_tells_user_and_developer_and_is_logged(self, boom, bot, session, caplog):
        await fire(boom, bot)
        assert session.texts_to(U) == [texts.ERROR_GENERIC]
        dev = session.texts_to(tf.DEVELOPER_ID)
        assert len(dev) == 1 and "RuntimeError" in dev[0] and "kutilmagan xato" in dev[0]
        assert "chat: 5" in dev[0] and "user: 5" in dev[0] and "update: message" in dev[0]
        rec = next(r for r in caplog.records if "Ushlanmagan xatolik" in r.message)
        assert rec.exc_info is not None

    async def test_group_error_does_not_spam_the_group(self, boom, bot, session):
        await feed(boom.dp, bot, tf.group_message(U, "salom"))
        assert not session.sent_to(tf.GROUP_ID) and len(session.texts_to(tf.DEVELOPER_ID)) == 1

    async def test_callback_error_is_shown_as_alert(self, boom, bot, session):
        await feed(boom.dp, bot, tf.callback(U, VoteCB(vote="yes", app_id=1).pack()))
        alert = session.of(AnswerCallbackQuery)[0]
        assert alert.text == texts.ERROR_GENERIC and alert.show_alert is True
        assert "update: callback_query" in session.texts_to(tf.DEVELOPER_ID)[0]

    async def test_developer_alert_is_html_escaped_and_truncated(self, boom, bot, session):
        boom.exc = RuntimeError("<b>" + "x" * 1000)
        await fire(boom, bot)
        text = session.texts_to(tf.DEVELOPER_ID)[0]
        assert "<b>xxx" not in text and "&lt;b&gt;" in text and len(text) < 600

    async def test_alerts_are_rate_limited_per_error_and_cooldown_expires(self, boom, bot, session):
        for _ in range(5):
            await fire(boom, bot)
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 1
        assert len(session.texts_to(U)) == 5  # foydalanuvchi har safar xabar oladi
        boom.exc = ValueError("boshqa")
        await fire(boom, bot)
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 2  # boshqa xato alohida hisoblanadi
        for key in errors._last_alert:
            errors._last_alert[key] -= errors.ALERT_COOLDOWN + 1
        await fire(boom, bot)
        assert len(session.texts_to(tf.DEVELOPER_ID)) == 3

    async def test_stale_alert_entries_are_purged_once_table_is_full(self, boom, bot, session, monkeypatch):
        monkeypatch.setattr(errors, "_LAST_ALERT_MAX", 3)
        for i in range(5):
            errors._last_alert[f"eski{i}"] = -10_000.0  # cooldown'i o'tgan
        await fire(boom, bot, "x")
        assert not any(k.startswith("eski") for k in errors._last_alert)
        assert len(errors._last_alert) == 1

    async def test_no_developers_configured(self, boom, bot, session, monkeypatch):
        monkeypatch.setattr(errors, "DEVELOPER_IDS", [])
        await fire(boom, bot)
        assert session.texts_to(U) == [texts.ERROR_GENERIC]

    @pytest.mark.parametrize("blocked,delivered", [(tf.DEVELOPER_ID, U), (U, tf.DEVELOPER_ID)])
    async def test_undeliverable_message_does_not_hide_the_other_one(self, boom, bot, session, blocked, delivered):
        session.errors[SendMessage] = lambda m: tf.forbidden(m) if m.chat_id == blocked else None
        await fire(boom, bot)
        assert len(session.texts_to(delivered)) == 1
