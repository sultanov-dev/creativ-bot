"""handlers/join.py, anketa.py, start.py: arizachi tomonidagi savollar oqimi."""
from typing import cast

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import SendMessage
from aiogram.types import Contact

import database as dbm
import texts
from states import Form
from tests import telegram_fakes as tf
from tests.flow import ANSWERS, assert_no_errors, feed, fill_form, get_app, start_application, state_of, status_of

U = 1


async def at_step(dp: Dispatcher, bot: Bot, step: int) -> None:
    """Join request + `step` ta javob; keyingi savolga tayyor holat (sessiya tozalanadi)."""
    await feed(dp, bot, tf.join_request(U))
    for a in ANSWERS[:step]:
        await feed(dp, bot, tf.private_message(U, a))
    cast(tf.FakeSession, bot.session).clear()


async def profile() -> dict:
    p = await dbm.get_profile(U)
    assert p is not None
    return p


async def app_count() -> int:
    row = await (await (await dbm.get_db()).execute("SELECT COUNT(*) FROM applications")).fetchone()
    assert row is not None
    return row[0]


class TestJoinRequest:
    async def test_new_applicant_gets_welcome_and_first_question(self, dp, bot, session):
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert sent[0].startswith("Assalomu alaykum") and sent[1] == texts.ASK_FULL_NAME
        state, data = await state_of(dp, bot)
        assert state == Form.full_name.state
        assert data == {"group_id": tf.GROUP_ID, "user_id": U, "username": f"user{U}"}
        assert_no_errors(session)

    async def test_active_application_blocks_questionnaire_only_in_its_group(self, dp, bot, session):
        app_id = await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")
        assert app_id is not None
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.ALREADY_APPLIED]
        assert (await state_of(dp, bot))[0] is None and await status_of(app_id) == "pending"
        await feed(dp, bot, tf.join_request(U, chat_id=tf.GROUP_ID - 1))  # boshqa guruh mustaqil
        assert (await state_of(dp, bot))[0] == Form.full_name.state

    @pytest.mark.parametrize("status,note", [
        ("rejected", texts.REJOIN_AFTER_REJECTION),
        ("expired", texts.REJOIN_AFTER_EXPIRED),
        ("failed", texts.REJOIN_AFTER_FAILED),
    ])
    async def test_last_application_rejected_expired_or_failed_means_fresh_questionnaire(
        self, dp, bot, session, status, note
    ):
        await dbm.change_status(await start_application(dp, bot), "pending", status)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        # eski ma'lumotlar ko'rsatilmaydi: qisqa xabar va anketa boshidan
        assert session.texts_to(U) == [note, texts.ASK_FULL_NAME]
        state, data = await state_of(dp, bot)
        assert state == Form.full_name.state and "full_name" not in data and "age" not in data
        assert len(note) < 80

    async def test_rejected_user_applies_again_new_answers_replace_profile_then_expired_starts_fresh(
        self, dp, bot, session
    ):
        first = await start_application(dp, bot)
        await dbm.change_status(first, "pending", "rejected")
        second = await start_application(dp, bot, answers=["Bobur Aliyev", texts.SKIP_BUTTON, "33", "Dizayner",
                                                           "Yangi", "Sabab"])
        assert second != first
        p = await profile()
        assert p["full_name"] == "Bobur Aliyev" and p["age"] == 33
        await dbm.change_status(second, "pending", "expired")  # eng oxirgi holat hisobga olinadi
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U)[0] == texts.REJOIN_AFTER_EXPIRED
        assert (await state_of(dp, bot))[0] == Form.full_name.state

    async def test_accepted_application_shows_saved_profile(self, dp, bot, session):
        await dbm.change_status(await start_application(dp, bot), "pending", "accepted")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert (await state_of(dp, bot))[0] == Form.review.state
        assert not any(t in session.texts_to(U) for t in texts.REJOIN_NOTES.values())

    async def test_status_is_per_group(self, dp, bot, session):
        await dbm.change_status(await start_application(dp, bot), "pending", "expired")
        session.clear()
        await feed(dp, bot, tf.join_request(U, tf.GROUP_ID - 9))  # boshqa guruhda hali arizasi yo'q
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_second_join_request_mid_questionnaire_keeps_progress(self, dp, bot, session):
        await at_step(dp, bot, 2)
        await feed(dp, bot, tf.join_request(U))
        state, data = await state_of(dp, bot)
        assert state == Form.age.state and data["full_name"] == "Aziz Karimov"
        assert session.texts_to(U) == [texts.FINISH_FORM_FIRST, texts.ASK_AGE]


class TestEachStepRejectsBadInput:
    @pytest.mark.parametrize(
        "step,bad,warning",
        [
            (0, "Aziz", texts.WRONG_NAME),
            (0, "12 34", texts.WRONG_NAME),
            (0, "/bogus now", texts.WRONG_NAME),
            (1, "abc", texts.WRONG_PHONE),
            (1, "12345", texts.WRONG_PHONE),
            (2, "yigirma", texts.WRONG_AGE),
            (2, "9", texts.WRONG_AGE),
            (2, "101", texts.WRONG_AGE),
            (2, "0", texts.WRONG_AGE),
            (3, "x" * 801, texts.TOO_LONG),
            (4, "x" * 801, texts.TOO_LONG),
            (5, "x" * 801, texts.TOO_LONG),
            (1, None, texts.ONLY_TEXT),
            (5, None, texts.ONLY_TEXT),
        ],
    )
    async def test_warning_and_state_does_not_advance(self, dp, bot, session, step, bad, warning):
        await at_step(dp, bot, step)
        before = (await state_of(dp, bot))[0]
        await feed(dp, bot, tf.private_message(U, bad))
        assert session.texts_to(U) == [warning]
        assert (await state_of(dp, bot))[0] == before
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None

    @pytest.mark.parametrize("step", [0, 2, 3, 4])
    async def test_non_text_message_gets_only_text_notice(self, dp, bot, session, step):
        await at_step(dp, bot, step)
        await feed(dp, bot, tf.private_message(U, None))
        assert session.texts_to(U) == [texts.ONLY_TEXT]


class TestAcceptedValues:
    @pytest.mark.parametrize("step,answer,state,key,value", [
        (2, "10", Form.job, "age", 10),  # chegara yoshlar
        (2, "100", Form.job, "age", 100),
        (2, "men 25 yoshdaman", Form.job, "age", 25),  # gapdan raqam ajratiladi
        (3, "x" * 800, Form.about, "job", "x" * 800),  # aniq 800 belgi
        (1, texts.SKIP_BUTTON, Form.age, "phone", None),
        (1, "+998 90 123-45-67", Form.age, "phone", "+998901234567"),  # normallashtiriladi
    ])
    async def test_valid_answer_is_stored_and_advances(self, dp, bot, session, step, answer, state, key, value):
        await at_step(dp, bot, step)
        await feed(dp, bot, tf.private_message(U, answer))
        st, data = await state_of(dp, bot)
        assert st == state.state and data[key] == value

    async def test_own_contact_is_accepted_and_plus_added(self, dp, bot, session):
        await at_step(dp, bot, 1)
        await feed(dp, bot, tf.private_message(U, None, contact=Contact(phone_number="998901234567", first_name="A", user_id=U)))
        state, data = await state_of(dp, bot)
        assert state == Form.age.state and data["phone"] == "+998901234567"

    @pytest.mark.parametrize("contact_user_id", [555, None])  # begona yoki user_id'siz (forward) kontakt
    async def test_foreign_contact_is_refused(self, dp, bot, session, contact_user_id):
        await at_step(dp, bot, 1)
        contact = Contact(phone_number="998901234567", first_name="A", user_id=contact_user_id)
        await feed(dp, bot, tf.private_message(U, None, contact=contact))
        assert session.texts_to(U) == [texts.WRONG_CONTACT]
        assert (await state_of(dp, bot))[0] == Form.phone.state

    async def test_html_in_answers_is_escaped_in_stored_anketa(self, dp, bot, session):
        answers = ["Aziz Karimov", texts.SKIP_BUTTON, "25", "<script>x</script>", "a & b", "<i>sabab</i>"]
        app = await get_app(await start_application(dp, bot, answers=answers))
        assert "<script>" not in app["anketa"] and "&lt;script&gt;" in app["anketa"]
        assert "<i>sabab</i>" not in app["anketa"]
        assert_no_errors(session)


class TestCompletion:
    async def test_full_flow_creates_application_profile_and_notifies_admins(self, dp, bot, session):
        app_id = await start_application(dp, bot, answers=["Aziz Karimov", "+998901234567", "25",
                                                           "Dasturchi", "Haqida", "Sabab"])
        app = await get_app(app_id)
        assert (app["status"], app["user_id"], app["group_id"]) == ("pending", U, tf.GROUP_ID)
        assert app["full_name"] == "Aziz Karimov" and app["tg_username"] == "user1"
        assert app["phone"] == "+998901234567"
        assert "+998901234567" not in app["anketa"]  # guruhga ketadigan matnda telefon yo'q
        p = await profile()
        assert p["full_name"] == "Aziz Karimov" and p["age"] == 25

        for admin in (tf.ADMIN_ID, tf.ADMIN2_ID):
            msg = session.sent_to(admin)[0]
            assert "+998901234567" in (msg.text or "") and msg.reply_markup is not None
        mine = session.texts_to(U)
        assert mine[-1] == texts.THANKS and "+998901234567" in mine[-2]
        assert session.sent_to(tf.GROUP_ID) == []  # hali ovozga qo'yilmagan
        assert (await state_of(dp, bot)) == (None, {})
        assert_no_errors(session)

    async def test_no_admins_configured(self, dp, bot, session, monkeypatch):
        import utils.admin as admin_utils

        monkeypatch.setattr(admin_utils, "ADMIN_IDS", [])  # ADMIN_IDS ham, guruh adminlari ham yo'q
        await fill_form(dp, bot)
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None
        assert (await state_of(dp, bot))[0] is None

    async def test_no_admin_can_be_reached_closes_application_for_retry(self, dp, bot, session):
        session.errors[SendMessage] = lambda m: (
            tf.forbidden(m) if m.chat_id in (tf.ADMIN_ID, tf.ADMIN2_ID) else None
        )
        await fill_form(dp, bot)
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None  # failed: qayta urinish mumkin
        row = await (await (await dbm.get_db()).execute("SELECT status FROM applications")).fetchone()
        assert row is not None and row["status"] == "failed"

    async def test_one_reachable_admin_is_enough(self, dp, bot, session):
        session.errors[SendMessage] = lambda m: tf.forbidden(m) if m.chat_id == tf.ADMIN_ID else None
        app_id = await start_application(dp, bot)
        assert await status_of(app_id) == "pending"
        assert session.texts_to(U)[-1] == texts.THANKS

    async def test_missing_group_id_in_state_is_handled(self, dp, bot, session):
        ctx = dp.fsm.get_context(bot, chat_id=U, user_id=U)
        await ctx.set_state(Form.join_group)
        await ctx.set_data({"full_name": "Aziz Karimov", "age": 25, "job": "j", "about": "a"})
        await feed(dp, bot, tf.private_message(U, "sabab"))
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC
        assert await dbm.get_profile(U) is not None  # javoblar baribir saqlangan

    async def test_existing_active_application_at_the_end(self, dp, bot, session):
        await at_step(dp, bot, 5)
        await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")  # shu orada boshqa ariza paydo bo'ldi
        await feed(dp, bot, tf.private_message(U, "Sabab"))
        assert session.texts_to(U) == [texts.ALREADY_APPLIED]
        assert session.sent_to(tf.ADMIN_ID) == []

    async def test_double_send_of_last_answer_creates_single_application(self, dp, bot, session):
        await at_step(dp, bot, 5)
        await feed(dp, bot, tf.private_message(U, "Sabab"))
        await feed(dp, bot, tf.private_message(U, "Sabab"))  # holat tozalangan: ikkinchisi e'tiborsiz
        assert await app_count() == 1 and len(session.sent_to(tf.ADMIN_ID)) == 1

    async def test_admin_gets_vote_and_reject_buttons_with_clear_texts(self, dp, bot, session):
        await start_application(dp, bot)
        markup = session.sent_to(tf.ADMIN_ID)[0].reply_markup
        assert markup is not None
        buttons = [(b.text, (b.callback_data or "").split(":")[1]) for row in markup.inline_keyboard for b in row]
        assert buttons == [("🗳 Ovozga qo'yish", "accept"), ("❌ Rad etish", "reject")]


class TestStartCommand:
    async def test_fresh_user_gets_greeting_with_escaped_name(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert "Salom" in session.texts_to(U)[0]
        raw = tf.private_message(U, "/start").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"]["from"]["first_name"] = "<b>X</b>"
        await dp.feed_raw_update(bot, raw)
        assert "&lt;b&gt;X" in session.texts_to(U)[-1]

    @pytest.mark.parametrize("step,question", [
        (0, texts.ASK_FULL_NAME), (1, texts.ASK_PHONE), (2, texts.ASK_AGE),
        (3, texts.ASK_JOB), (4, texts.ASK_ABOUT), (5, texts.ASK_REASON),
    ])
    async def test_start_mid_questionnaire_repeats_current_question(self, dp, bot, session, step, question):
        await at_step(dp, bot, step)
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert session.texts_to(U) == ["Anketani to'ldirishda davom etamiz 👇", question]
        state, data = await state_of(dp, bot)
        assert state == list(Form.__states__)[step].state
        assert step < 1 or data["full_name"] == "Aziz Karimov"  # yig'ilgan javoblar yo'qolmaydi

    async def test_admin_start_only_greets(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "/start"))
        assert len(session.texts_to(tf.ADMIN_ID)) == 1
        assert_no_errors(session)
