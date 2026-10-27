"""handlers/join.py, anketa.py, start.py: arizachi tomonidagi savollar oqimi."""
import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Contact

import database as dbm
import texts
from states import Form
from tests import telegram_fakes as tf
from tests.flow import ANSWERS, assert_no_errors, feed, start_application, status_of

U = 1


async def state_of(dp, bot, user=U):
    ctx = dp.fsm.get_context(bot, chat_id=user, user_id=user)
    return await ctx.get_state(), await ctx.get_data()


async def at_step(dp, bot, step: int, user=U):
    """Join request + `step` ta javob; keyingi savolga tayyor holat."""
    await feed(dp, bot, tf.join_request(user))
    for a in ANSWERS[:step]:
        await feed(dp, bot, tf.private_message(user, a))
    session = bot.session
    session.clear()


class TestJoinRequest:
    async def test_new_applicant_gets_welcome_and_first_question(self, dp, bot, session):
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert sent[0].startswith("Assalomu alaykum") and sent[1] == texts.ASK_FULL_NAME
        state, data = await state_of(dp, bot)
        assert state == Form.full_name.state
        assert data == {"group_id": tf.GROUP_ID, "user_id": U}
        assert_no_errors(session)

    async def test_active_application_blocks_new_questionnaire(self, dp, bot, session):
        app_id = await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.ALREADY_APPLIED]
        assert (await state_of(dp, bot))[0] is None
        assert await status_of(app_id) == "pending"

    async def test_other_group_request_is_independent(self, dp, bot, session):
        await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")
        await feed(dp, bot, tf.join_request(U, chat_id=tf.GROUP_ID - 1))
        assert (await state_of(dp, bot))[0] == Form.full_name.state

    async def test_rejoin_after_rejection_starts_fresh_application(self, dp, bot, session):
        first = await start_application(dp, bot)
        await dbm.change_status(first, "pending", "rejected")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        # profil saqlangan: savollar o'rniga ko'rib chiqish
        assert (await state_of(dp, bot))[0] == Form.review.state

    async def test_second_join_request_mid_questionnaire_restarts_it(self, dp, bot, session):
        await at_step(dp, bot, 3)
        await feed(dp, bot, tf.join_request(U))
        state, data = await state_of(dp, bot)
        assert state == Form.full_name.state and "full_name" not in data


class TestEachStepRejectsBadInput:
    @pytest.mark.parametrize(
        "step,bad,warning",
        [
            (0, "Aziz", texts.WRONG_NAME),
            (0, "12 34", texts.WRONG_NAME),
            (0, "/bogus now", texts.WRONG_NAME),
            (1, "ab", texts.WRONG_USERNAME),
            (1, "1azizbek", texts.WRONG_USERNAME),
            (2, "abc", texts.WRONG_PHONE),
            (2, "12345", texts.WRONG_PHONE),
            (3, "yigirma", texts.WRONG_AGE),
            (3, "9", texts.WRONG_AGE),
            (3, "101", texts.WRONG_AGE),
            (3, "0", texts.WRONG_AGE),
            (4, "x" * 801, texts.TOO_LONG),
            (5, "x" * 801, texts.TOO_LONG),
            (6, "x" * 801, texts.TOO_LONG),
        ],
    )
    async def test_warning_and_state_does_not_advance(self, dp, bot, session, step, bad, warning):
        await at_step(dp, bot, step)
        before = (await state_of(dp, bot))[0]
        await feed(dp, bot, tf.private_message(U, bad))
        assert session.texts_to(U) == [warning]
        assert (await state_of(dp, bot))[0] == before
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None

    @pytest.mark.parametrize("step", range(7))
    async def test_non_text_message_gets_only_text_notice(self, dp, bot, session, step):
        await at_step(dp, bot, step)
        before = (await state_of(dp, bot))[0]
        await feed(dp, bot, tf.private_message(U, None))
        assert session.texts_to(U) == [texts.ONLY_TEXT]
        assert (await state_of(dp, bot))[0] == before


class TestAcceptedValues:
    async def test_boundary_ages(self, dp, bot, session):
        for age, ok in [("10", True), ("100", True), ("9", False), ("101", False)]:
            await at_step(dp, bot, 3)
            await feed(dp, bot, tf.private_message(U, age))
            assert ((await state_of(dp, bot))[0] == Form.job.state) is ok

    async def test_age_extracted_from_sentence(self, dp, bot, session):
        await at_step(dp, bot, 3)
        await feed(dp, bot, tf.private_message(U, "men 25 yoshdaman"))
        assert (await state_of(dp, bot))[1]["age"] == 25

    async def test_exactly_800_chars_is_accepted(self, dp, bot, session):
        await at_step(dp, bot, 4)
        await feed(dp, bot, tf.private_message(U, "x" * 800))
        assert (await state_of(dp, bot))[0] == Form.about.state

    async def test_username_is_stored_without_at(self, dp, bot, session):
        await at_step(dp, bot, 1)
        await feed(dp, bot, tf.private_message(U, "@azizbek"))
        assert (await state_of(dp, bot))[1]["username"] == "azizbek"

    async def test_skip_username_and_phone(self, dp, bot, session):
        await at_step(dp, bot, 1)
        await feed(dp, bot, tf.private_message(U, texts.SKIP_BUTTON))
        await feed(dp, bot, tf.private_message(U, "/skip"))
        state, data = await state_of(dp, bot)
        assert state == Form.age.state and data["username"] is None and data["phone"] is None

    async def test_phone_typed_is_normalised(self, dp, bot, session):
        await at_step(dp, bot, 2)
        await feed(dp, bot, tf.private_message(U, "+998 90 123-45-67"))
        assert (await state_of(dp, bot))[1]["phone"] == "+998901234567"

    async def test_own_contact_is_accepted_and_plus_added(self, dp, bot, session):
        await at_step(dp, bot, 2)
        contact = Contact(phone_number="998901234567", first_name="A", user_id=U)
        await feed(dp, bot, tf.private_message(U, None, contact=contact))
        state, data = await state_of(dp, bot)
        assert state == Form.age.state and data["phone"] == "+998901234567"

    async def test_foreign_contact_is_refused(self, dp, bot, session):
        await at_step(dp, bot, 2)
        contact = Contact(phone_number="998901234567", first_name="A", user_id=555)
        await feed(dp, bot, tf.private_message(U, None, contact=contact))
        assert session.texts_to(U) == [texts.WRONG_CONTACT]
        assert (await state_of(dp, bot))[0] == Form.phone.state

    async def test_contact_without_user_id_is_refused(self, dp, bot, session):
        # forward qilingan/qo'lda yozilgan kontaktda user_id bo'lmasligi mumkin: o'zimniki deb qabul qilinmasin
        await at_step(dp, bot, 2)
        contact = Contact(phone_number="998901234567", first_name="A")
        await feed(dp, bot, tf.private_message(U, None, contact=contact))
        assert session.texts_to(U) == [texts.WRONG_CONTACT]

    async def test_html_in_answers_is_escaped_in_group_and_admin_texts(self, dp, bot, session):
        answers = ["<b>Aziz</b> Karimov".replace("<b>", "").replace("</b>", ""), texts.SKIP_BUTTON, texts.SKIP_BUTTON,
                   "25", "<script>x</script>", "a & b", "<i>sabab</i>"]
        app_id = await start_application(dp, bot, answers=answers)
        app = await dbm.get_application(app_id)
        assert "<script>" not in app["anketa"] and "&lt;script&gt;" in app["anketa"]
        assert "<i>sabab</i>" not in app["anketa"]
        assert_no_errors(session)


class TestCompletion:
    async def test_full_flow_creates_application_and_notifies_admins(self, dp, bot, session):
        app_id = await start_application(dp, bot, answers=["Aziz Karimov", "@azizbek", "+998901234567", "25",
                                                           "Dasturchi", "Haqida", "Sabab"])
        assert app_id is not None
        app = await dbm.get_application(app_id)
        assert (app["status"], app["user_id"], app["group_id"]) == ("pending", U, tf.GROUP_ID)
        assert app["full_name"] == "Aziz Karimov" and app["tg_username"] == "azizbek"
        assert app["phone"] == "+998901234567"
        assert "+998901234567" not in app["anketa"]  # guruhga ketadigan matnda telefon yo'q

        for admin in (tf.ADMIN_ID, tf.ADMIN2_ID):
            msg = session.sent_to(admin)[0]
            assert "+998901234567" in msg.text and msg.reply_markup is not None
        mine = session.texts_to(U)
        assert mine[-1] == texts.THANKS and "+998901234567" in mine[-2]
        assert session.sent_to(tf.GROUP_ID) == []  # hali ovozga qo'yilmagan
        assert (await state_of(dp, bot)) == (None, {})
        assert_no_errors(session)

    async def test_profile_saved_on_completion(self, dp, bot, session):
        await start_application(dp, bot)
        profile = await dbm.get_profile(U)
        assert profile["full_name"] == "Aziz Karimov" and profile["age"] == 25 and profile["phone"] is None

    async def test_two_applicants_are_independent(self, dp, bot, session):
        a = await start_application(dp, bot, user_id=1)
        b = await start_application(dp, bot, user_id=2, answers=["Bobur Aliyev"] + ANSWERS[1:])
        assert a != b
        assert (await dbm.get_application(b))["full_name"] == "Bobur Aliyev"

    async def test_no_admins_configured(self, dp, bot, session, monkeypatch):
        import handlers.anketa as anketa

        monkeypatch.setattr(anketa, "ADMIN_IDS", [])
        await start_application(dp, bot)
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None
        assert (await state_of(dp, bot))[0] is None

    async def test_no_admin_can_be_reached_closes_application_for_retry(self, dp, bot, session):
        session.errors[SendMessage] = lambda m: (
            TelegramForbiddenError(method=m, message="Forbidden: bot can't initiate conversation")
            if m.chat_id in (tf.ADMIN_ID, tf.ADMIN2_ID) else None
        )
        await feed(dp, bot, tf.join_request(U))
        for a in ANSWERS:
            await feed(dp, bot, tf.private_message(U, a))
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None  # failed: qayta urinish mumkin
        row = await (await (await dbm.get_db()).execute("SELECT status FROM applications")).fetchone()
        assert row["status"] == "failed"

    async def test_one_reachable_admin_is_enough(self, dp, bot, session):
        session.errors[SendMessage] = lambda m: (
            TelegramForbiddenError(method=m, message="Forbidden") if m.chat_id == tf.ADMIN_ID else None
        )
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
        await at_step(dp, bot, 6)
        await dbm.create_application(U, tf.GROUP_ID, "A B", "x\n")  # shu orada boshqa ariza paydo bo'ldi
        await feed(dp, bot, tf.private_message(U, "Sabab"))
        assert session.texts_to(U) == [texts.ALREADY_APPLIED]
        assert session.sent_to(tf.ADMIN_ID) == []

    async def test_double_send_of_last_answer_creates_single_application(self, dp, bot, session):
        await at_step(dp, bot, 6)
        await feed(dp, bot, tf.private_message(U, "Sabab"))
        await feed(dp, bot, tf.private_message(U, "Sabab"))  # holat tozalangan: ikkinchisi e'tiborsiz
        rows = await (await (await dbm.get_db()).execute("SELECT COUNT(*) FROM applications")).fetchone()
        assert rows[0] == 1
        assert len(session.sent_to(tf.ADMIN_ID)) == 1


class TestStartCommand:
    async def test_fresh_user_gets_greeting(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert "Salom" in session.texts_to(U)[0]

    async def test_greeting_escapes_name(self, dp, bot, session):
        raw = tf.private_message(U, "/start").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"]["from"]["first_name"] = "<b>X</b>"
        await dp.feed_raw_update(bot, raw)
        assert "&lt;b&gt;X" in session.texts_to(U)[0]

    @pytest.mark.parametrize("step,question", [
        (0, texts.ASK_FULL_NAME), (1, texts.ASK_USERNAME), (2, texts.ASK_PHONE), (3, texts.ASK_AGE),
        (4, texts.ASK_JOB), (5, texts.ASK_ABOUT), (6, texts.ASK_REASON),
    ])
    async def test_start_mid_questionnaire_repeats_current_question(self, dp, bot, session, step, question):
        await at_step(dp, bot, step)
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert session.texts_to(U) == ["Anketani to'ldirishda davom etamiz 👇", question]
        assert (await state_of(dp, bot))[0] == list(Form.__states__)[step].state

    async def test_start_does_not_lose_collected_answers(self, dp, bot, session):
        await at_step(dp, bot, 3)
        await feed(dp, bot, tf.private_message(U, "/start"))
        assert (await state_of(dp, bot))[1]["full_name"] == "Aziz Karimov"

    async def test_admin_start_only_greets(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(tf.ADMIN_ID, "/start"))
        assert len(session.texts_to(tf.ADMIN_ID)) == 1
        assert_no_errors(session)
