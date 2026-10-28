"""handlers/profile.py + utils/applications.py: saqlangan anketa bilan qayta qo'shilish."""
import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import ReplyKeyboardMarkup

import database as dbm
import texts
from keyboards.profile import FIELD_LABELS
from states import Form
from tests import telegram_fakes as tf
from tests.flow import admin_accept, assert_no_errors, feed, start_application, state_of, status_of
from tests.telegram_fakes import FakeSession

U = 1
PHONE_ANSWERS = ["Aziz Karimov", "+998901234567", "25", "j", "a", "s"]


async def rejoin(dp: Dispatcher, bot: Bot, session: FakeSession, group: int = tf.GROUP_ID, answers=None) -> int:
    """Birinchi ariza qabul qilingan (foydalanuvchi keyin chiqib ketgan), qayta qo'shilish so'rovi yuboradi."""
    first = await start_application(dp, bot, user_id=U, answers=answers)
    await dbm.change_status(first, "pending", "accepted")
    session.clear()
    await feed(dp, bot, tf.join_request(U, group))
    return first


async def say(dp: Dispatcher, bot: Bot, text: str) -> None:
    await feed(dp, bot, tf.private_message(U, text))


async def active() -> dict:
    app = await dbm.get_active_application(U, tf.GROUP_ID)
    assert app is not None
    return app


async def profile() -> dict:
    p = await dbm.get_profile(U)
    assert p is not None
    return p


def keyboard_labels(msg: SendMessage) -> list[str]:
    markup = msg.reply_markup
    assert isinstance(markup, ReplyKeyboardMarkup)
    return [b.text for row in markup.keyboard for b in row]


class TestReview:
    async def test_saved_profile_is_shown_with_two_buttons(self, dp, bot, session):
        await rejoin(dp, bot, session, answers=PHONE_ANSWERS)
        msg = session.sent_to(U)[0]
        assert "Aziz Karimov" in (msg.text or "") and "+998901234567" in (msg.text or "")  # telefon egasiga ko'rinadi
        assert keyboard_labels(msg) == [texts.PROFILE_EDIT_BUTTON, texts.PROFILE_KEEP_BUTTON]
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_free_text_and_start_in_review(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.clear()
        await say(dp, bot, "salom")
        assert session.texts_to(U) == [texts.PROFILE_USE_BUTTONS]
        await say(dp, bot, "/start")
        assert "Siz avval anketa to'ldirgansiz" in session.texts_to(U)[-1]
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_stale_keep_button_without_state_does_nothing_harmful(self, dp, bot, session):
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert not any("ovoz" in t for t in session.texts_to(U))
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None


class TestKeep:
    async def test_keep_goes_to_admin_review_first_never_straight_to_the_group(self, dp, bot, session):
        first = await rejoin(dp, bot, session, answers=PHONE_ANSWERS)
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        app = await active()
        assert app["status"] == "pending" and app["id"] != first and await status_of(first) == "accepted"
        assert not session.sent_to(tf.GROUP_ID)  # guruhga hech narsa ketmadi
        admin_msg = session.sent_to(tf.ADMIN_ID)[-1]
        assert "+998901234567" in (admin_msg.text or "") and admin_msg.reply_markup is not None  # Ovozga qo'yish / Rad
        assert session.texts_to(U)[-1] == texts.THANKS and (await state_of(dp, bot)) == (None, {})
        # admin tasdiqlagandan keyingina guruhga ovozga qo'yiladi (telefonsiz)
        session.clear()
        await admin_accept(dp, bot, app["id"])
        assert await status_of(app["id"]) == "voting"
        assert "+998901234567" not in (session.sent_to(tf.GROUP_ID)[0].text or "")
        assert_no_errors(session)

    async def test_edited_saved_profile_is_checked_and_goes_to_admins(self, dp, bot, session, review_ai):
        """Saqlangan anketa o'zgartirilsa ham: bot + AI tekshiruvi, keyin adminga (guruhga emas)."""
        await rejoin(dp, bot, session)
        await say(dp, bot, texts.PROFILE_EDIT_BUTTON)
        await say(dp, bot, FIELD_LABELS["job"])
        await say(dp, bot, "porno aktyorman")  # javobda so'kinish yo'q: o'tadi, Tasdiqlashda ushlanadi
        review_ai.calls.clear()
        session.clear()
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert session.texts_to(U)[-1] == texts.ASK_JOB and not review_ai.calls  # bot o'zi ushladi
        await say(dp, bot, "Backend dasturchi")
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert len(review_ai.calls) == 1  # endi AI tekshirdi
        assert (await active())["status"] == "pending" and session.sent_to(tf.ADMIN_ID)
        assert not session.sent_to(tf.GROUP_ID)

    async def test_username_is_refreshed_from_telegram_and_never_shown(self, dp, bot, session):
        await dbm.save_profile(U, {"full_name": "Aziz Karimov", "username": "old_name", "phone": None, "age": 25,
                                   "job": "j", "about": "a", "join_group": "s"})
        await feed(dp, bot, tf.join_request(U))
        shown = session.sent_to(U)[0].text or ""
        assert "old_name" not in shown and f"user{U}" not in shown
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert (await active())["tg_username"] == f"user{U}"

    async def test_unreachable_admins_mark_failed_and_allow_retry(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.errors[SendMessage] = lambda m: tf.bad_request("Bad Request: chat not found", m) if m.chat_id != U else None
        session.clear()
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert session.texts_to(U) == [texts.ANKETA_CHECKING, texts.ERROR_GENERIC]
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None and not session.sent_to(tf.GROUP_ID)
        # ariza "failed" bo'ldi: qayta qo'shilganda eski ma'lumot ko'rsatilmaydi, anketa boshidan
        session.errors.clear()
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.REJOIN_AFTER_FAILED, texts.ASK_FULL_NAME]

    async def test_keep_when_application_already_open(self, dp, bot, session):
        await rejoin(dp, bot, session)
        await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")  # shu orada boshqa ariza paydo bo'ldi
        session.clear()
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert session.texts_to(U) == [texts.ANKETA_CHECKING, texts.ALREADY_APPLIED]

    async def test_keep_without_group_id_in_state(self, dp, bot, session):
        ctx = dp.fsm.get_context(bot, chat_id=U, user_id=U)
        await ctx.set_state(Form.review)
        await ctx.set_data({"full_name": "Aziz Karimov"})
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert session.texts_to(U) == [texts.ANKETA_CHECKING, texts.ERROR_GENERIC]
        assert (await state_of(dp, bot))[0] is None

    async def test_legacy_profile_with_first_and_last_name_works(self, dp, bot, session):
        await dbm.save_profile(U, {"first_name": "Aziz", "last_name": "Karimov", "age": 30, "job": "j",
                                   "about": "a", "join_group": "s", "username": None, "phone": None})
        await feed(dp, bot, tf.join_request(U))
        session.clear()
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        app = await active()
        assert app["full_name"] == "Aziz Karimov" and app["first_name"] == "Aziz" and app["last_name"] == "Karimov"
        assert_no_errors(session)

    async def test_rejoin_for_another_group_uses_profile_for_that_group(self, dp, bot, session):
        await start_application(dp, bot, user_id=U)  # birinchi guruhdagi ariza hali ochiq
        session.clear()
        other = tf.GROUP_ID - 5
        await feed(dp, bot, tf.join_request(U, other))
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        app = await dbm.get_active_application(U, other)
        assert app is not None and app["group_id"] == other and app["status"] == "pending"
        assert not session.sent_to(other)  # avval adminga, guruhga emas


class TestEdit:
    async def _into_edit(self, dp: Dispatcher, bot: Bot, session: FakeSession, answers=None) -> None:
        await rejoin(dp, bot, session, answers=answers)
        await say(dp, bot, texts.PROFILE_EDIT_BUTTON)

    async def test_edit_opens_field_menu_back_and_free_text(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.clear()
        await say(dp, bot, texts.PROFILE_EDIT_BUTTON)
        msg = session.sent_to(U)[0]
        assert msg.text == texts.PROFILE_PICK_FIELD
        labels = keyboard_labels(msg)
        assert set(FIELD_LABELS.values()) <= set(labels) and labels[-1] == texts.PROFILE_BACK_BUTTON
        assert (await state_of(dp, bot))[0] == Form.pick_field.state
        session.clear()
        await say(dp, bot, "yosh")
        assert session.texts_to(U) == [texts.PROFILE_USE_BUTTONS]
        session.clear()
        await say(dp, bot, texts.PROFILE_BACK_BUTTON)
        assert (await state_of(dp, bot))[0] == Form.review.state
        assert "Siz avval anketa" in session.texts_to(U)[0]

    @pytest.mark.parametrize("field,question", [
        ("full_name", texts.ASK_FULL_NAME), ("phone", texts.ASK_PHONE),
        ("age", texts.ASK_AGE), ("job", texts.ASK_JOB), ("about", texts.ASK_ABOUT), ("join_group", texts.ASK_REASON),
    ])
    async def test_each_field_asks_its_question_in_editing_mode(self, dp, bot, session, field, question):
        await self._into_edit(dp, bot, session)
        session.clear()
        await say(dp, bot, FIELD_LABELS[field])
        assert session.texts_to(U) == [question]
        state, data = await state_of(dp, bot)
        assert state == getattr(Form, field).state and data["editing"] is True

    async def test_edit_saves_only_that_field_and_shows_review_again(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        before = await profile()
        await say(dp, bot, FIELD_LABELS["job"])
        session.clear()
        await say(dp, bot, "Dizayner")
        assert session.texts_to(U)[0] == texts.PROFILE_SAVED and "Dizayner" in session.texts_to(U)[1]
        assert await profile() == {**before, "job": "Dizayner"}
        state, data = await state_of(dp, bot)
        assert state == Form.review.state and data["editing"] is False

    async def test_validation_still_applies_while_editing(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await say(dp, bot, FIELD_LABELS["age"])
        session.clear()
        await say(dp, bot, "5")
        assert session.texts_to(U) == [texts.WRONG_AGE]
        assert (await state_of(dp, bot))[0] == Form.age.state
        assert (await profile())["age"] == 25

    async def test_clearing_optional_field_by_skip(self, dp, bot, session):
        await self._into_edit(dp, bot, session, answers=PHONE_ANSWERS)
        await say(dp, bot, FIELD_LABELS["phone"])
        await say(dp, bot, texts.SKIP_BUTTON)
        assert (await profile())["phone"] is None

    async def test_start_while_picking_field_returns_to_review_and_mid_edit_repeats_question(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        session.clear()
        await say(dp, bot, "/start")
        assert (await state_of(dp, bot))[0] == Form.review.state
        await say(dp, bot, texts.PROFILE_EDIT_BUTTON)
        await say(dp, bot, FIELD_LABELS["job"])
        session.clear()
        await say(dp, bot, "/start")
        assert session.texts_to(U)[-1] == texts.ASK_JOB

    async def test_edit_then_keep_submits_edited_data(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await say(dp, bot, FIELD_LABELS["about"])
        await say(dp, bot, "Yangi matn")
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        app = await active()
        assert "Yangi matn" in app["anketa"] and app["status"] == "pending"

    async def test_new_join_request_cancels_unfinished_edit(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await say(dp, bot, FIELD_LABELS["job"])
        await feed(dp, bot, tf.join_request(U, tf.GROUP_ID - 3))
        state, data = await state_of(dp, bot)
        assert state == Form.review.state and "editing" not in data
