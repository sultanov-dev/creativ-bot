"""handlers/profile.py + utils/applications.py: saqlangan anketa bilan qayta qo'shilish."""
import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

import database as dbm
import texts
from keyboards.profile import FIELD_LABELS
from states import Form
from tests import telegram_fakes as tf
from tests.flow import assert_no_errors, feed, start_application, status_of

U = 1


async def state_of(dp, bot, user=U):
    ctx = dp.fsm.get_context(bot, chat_id=user, user_id=user)
    return await ctx.get_state(), await ctx.get_data()


async def rejoin(dp, bot, session, group=tf.GROUP_ID):
    """Birinchi ariza qabul qilingan (foydalanuvchi keyin chiqib ketgan), qayta qo'shilish so'rovi yuboradi."""
    first = await start_application(dp, bot, user_id=U)
    await dbm.change_status(first, "pending", "accepted")
    session.clear()
    await feed(dp, bot, tf.join_request(U, group))
    return first


def keyboard_labels(msg):
    return [b.text for row in msg.reply_markup.keyboard for b in row]


class TestReview:
    async def test_saved_profile_is_shown_with_two_buttons(self, dp, bot, session):
        await rejoin(dp, bot, session)
        msg = session.sent_to(U)[0]
        assert "Aziz Karimov" in msg.text and "Dasturchi" in msg.text
        assert keyboard_labels(msg) == [texts.PROFILE_EDIT_BUTTON, texts.PROFILE_KEEP_BUTTON]
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_review_shows_phone_to_its_owner(self, dp, bot, session):
        first = await start_application(dp, bot, answers=["Aziz Karimov", "+998901234567",
                                                          "25", "j", "a", "s"])
        await dbm.change_status(first, "pending", "accepted")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert "+998901234567" in session.sent_to(U)[0].text

    async def test_free_text_in_review_asks_to_use_buttons(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "salom"))
        assert session.texts_to(U) == [texts.PROFILE_USE_BUTTONS]
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_start_in_review_reshows_review(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert "Siz avval anketa to'ldirgansiz" in session.texts_to(U)[0]

    async def test_stale_keep_button_without_state_does_nothing_harmful(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert not any("ovoz" in t for t in session.texts_to(U))
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None


class TestKeep:
    async def test_keep_goes_straight_to_group_vote_without_admin_review(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        app = await dbm.get_active_application(U, tf.GROUP_ID)
        assert app["status"] == "voting" and app["vote_message_id"]
        assert not session.sent_to(tf.ADMIN_ID) and len(session.sent_to(tf.GROUP_ID)) == 1
        assert session.texts_to(U) == [texts.REPEAT_APPLICATION_SENT]
        assert (await state_of(dp, bot)) == (None, {})
        assert_no_errors(session)

    async def test_username_is_refreshed_from_telegram_and_never_shown(self, dp, bot, session):
        await dbm.save_profile(U, {"full_name": "Aziz Karimov", "username": "old_name", "phone": None, "age": 25,
                                   "job": "j", "about": "a", "join_group": "s"})
        await feed(dp, bot, tf.join_request(U))
        assert "old_name" not in session.sent_to(U)[0].text and f"user{U}" not in session.sent_to(U)[0].text
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert (await dbm.get_active_application(U, tf.GROUP_ID))["tg_username"] == f"user{U}"

    async def test_group_message_has_no_phone(self, dp, bot, session):
        first = await start_application(dp, bot, answers=["Aziz Karimov", "+998901234567",
                                                          "25", "j", "a", "s"])
        await dbm.change_status(first, "pending", "accepted")
        await feed(dp, bot, tf.join_request(U))
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert "+998901234567" not in session.sent_to(tf.GROUP_ID)[0].text
        assert (await dbm.get_active_application(U, tf.GROUP_ID))["phone"] == "+998901234567"

    async def test_group_send_failure_marks_failed_and_allows_retry(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.errors[SendMessage] = lambda m: (
            TelegramBadRequest(method=m, message="Bad Request: no rights") if m.chat_id == tf.GROUP_ID else None
        )
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert session.texts_to(U) == [texts.ERROR_GENERIC]
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None
        # ariza "failed" bo'ldi: qayta qo'shilganda eski ma'lumot ko'rsatilmaydi, anketa boshidan
        session.errors.clear()
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.REJOIN_AFTER_FAILED, texts.ASK_FULL_NAME]

    async def test_keep_when_application_already_open(self, dp, bot, session):
        await rejoin(dp, bot, session)
        await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")  # shu orada boshqa ariza paydo bo'ldi
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert session.texts_to(U) == [texts.ALREADY_APPLIED]

    async def test_keep_without_group_id_in_state(self, dp, bot, session):
        ctx = dp.fsm.get_context(bot, chat_id=U, user_id=U)
        await ctx.set_state(Form.review)
        await ctx.set_data({"full_name": "Aziz Karimov"})
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert session.texts_to(U) == [texts.PROFILE_SAVED]
        assert (await state_of(dp, bot))[0] is None

    async def test_legacy_profile_with_first_and_last_name_works(self, dp, bot, session):
        await dbm.save_profile(U, {"first_name": "Aziz", "last_name": "Karimov", "age": 30, "job": "j",
                                   "about": "a", "join_group": "s", "username": None, "phone": None})
        await feed(dp, bot, tf.join_request(U))
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        app = await dbm.get_active_application(U, tf.GROUP_ID)
        assert app["full_name"] == "Aziz Karimov" and app["first_name"] == "Aziz" and app["last_name"] == "Karimov"
        assert_no_errors(session)

    async def test_rejoin_for_another_group_uses_profile_for_that_group(self, dp, bot, session):
        await start_application(dp, bot, user_id=U)  # birinchi guruhdagi ariza hali ochiq
        session.clear()
        other = tf.GROUP_ID - 5
        await feed(dp, bot, tf.join_request(U, other))
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert (await dbm.get_active_application(U, other))["group_id"] == other
        assert len(session.sent_to(other)) == 1


class TestEdit:
    async def _into_edit(self, dp, bot, session):
        await rejoin(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_EDIT_BUTTON))

    async def test_edit_opens_field_menu(self, dp, bot, session):
        await rejoin(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_EDIT_BUTTON))
        msg = session.sent_to(U)[0]
        assert msg.text == texts.PROFILE_PICK_FIELD
        labels = keyboard_labels(msg)
        assert set(FIELD_LABELS.values()) <= set(labels) and labels[-1] == texts.PROFILE_BACK_BUTTON
        assert (await state_of(dp, bot))[0] == Form.pick_field.state

    async def test_back_returns_to_review(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_BACK_BUTTON))
        assert (await state_of(dp, bot))[0] == Form.review.state
        assert "Siz avval anketa" in session.texts_to(U)[0]

    async def test_free_text_in_field_menu_asks_for_buttons(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "yosh"))
        assert session.texts_to(U) == [texts.PROFILE_USE_BUTTONS]

    @pytest.mark.parametrize("field,question", [
        ("full_name", texts.ASK_FULL_NAME), ("phone", texts.ASK_PHONE),
        ("age", texts.ASK_AGE), ("job", texts.ASK_JOB), ("about", texts.ASK_ABOUT), ("join_group", texts.ASK_REASON),
    ])
    async def test_each_field_asks_its_question_in_editing_mode(self, dp, bot, session, field, question):
        await self._into_edit(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS[field]))
        assert session.texts_to(U) == [question]
        state, data = await state_of(dp, bot)
        assert state == getattr(Form, field).state and data["editing"] is True

    async def test_edited_value_is_saved_and_review_shown_again(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["job"]))
        session.clear()
        await feed(dp, bot, tf.private_message(U, "Dizayner"))
        assert session.texts_to(U)[0] == texts.PROFILE_SAVED
        assert "Dizayner" in session.texts_to(U)[1]
        assert (await dbm.get_profile(U))["job"] == "Dizayner"
        state, data = await state_of(dp, bot)
        assert state == Form.review.state and data["editing"] is False

    async def test_other_fields_are_not_touched_by_an_edit(self, dp, bot, session):
        before = None
        await rejoin(dp, bot, session)
        before = await dbm.get_profile(U)
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_EDIT_BUTTON))
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["age"]))
        await feed(dp, bot, tf.private_message(U, "33"))
        after = await dbm.get_profile(U)
        assert after == {**before, "age": 33}

    async def test_validation_still_applies_while_editing(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["age"]))
        session.clear()
        await feed(dp, bot, tf.private_message(U, "5"))
        assert session.texts_to(U) == [texts.WRONG_AGE]
        assert (await state_of(dp, bot))[0] == Form.age.state
        assert (await dbm.get_profile(U))["age"] == 25

    async def test_clearing_optional_field_by_skip(self, dp, bot, session):
        first = await start_application(dp, bot, answers=["Aziz Karimov", "+998901234567", "25", "j", "a", "s"])
        await dbm.change_status(first, "pending", "accepted")
        await feed(dp, bot, tf.join_request(U))
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_EDIT_BUTTON))
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["phone"]))
        await feed(dp, bot, tf.private_message(U, texts.SKIP_BUTTON))
        assert (await dbm.get_profile(U))["phone"] is None

    async def test_start_while_picking_field_returns_to_review(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_start_mid_edit_repeats_the_question(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["job"]))
        session.clear()
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert session.texts_to(U)[-1] == texts.ASK_JOB

    async def test_edit_then_keep_submits_edited_data(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["about"]))
        await feed(dp, bot, tf.private_message(U, "Yangi matn"))
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        app = await dbm.get_active_application(U, tf.GROUP_ID)
        assert "Yangi matn" in app["anketa"] and app["status"] == "voting"

    async def test_new_join_request_cancels_unfinished_edit(self, dp, bot, session):
        await self._into_edit(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["job"]))
        await feed(dp, bot, tf.join_request(U, tf.GROUP_ID - 3))
        state, data = await state_of(dp, bot)
        assert state == Form.review.state and "editing" not in data

    async def test_status_after_keep_is_not_stuck_pending(self, dp, bot, session):
        first = await rejoin(dp, bot, session)
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        assert await status_of(first) == "accepted"
        app = await dbm.get_active_application(U, tf.GROUP_ID)
        assert app["id"] != first
