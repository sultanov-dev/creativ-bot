"""Yangi anketa: oxirida foydalanuvchiga ko'rsatiladi (Tasdiqlash / O'zgartirish), tasdiqlangach AI tekshiradi."""
import pytest
from aiogram.types import ReplyKeyboardMarkup

import database as dbm
import texts
from keyboards.profile import FIELD_LABELS
from tests import telegram_fakes as tf
from tests.flow import ANSWERS, feed, fill_form, start_application, state_of
from utils.ai import AIError
from utils.anketa_review import _parse

G = tf.GROUP_ID
U = 1
CONFIRM = texts.ANKETA_CONFIRM_BUTTON


async def say(dp, bot, text: str) -> None:
    await feed(dp, bot, tf.private_message(U, text))


def buttons(message) -> list[str]:
    markup = message.reply_markup
    assert isinstance(markup, ReplyKeyboardMarkup)  # inline emas, oddiy tugmalar
    return [b.text for row in markup.keyboard for b in row]


async def at_confirm(dp, bot, session) -> None:
    await fill_form(dp, bot, U, ANSWERS, confirm=False)
    session.clear()


class TestConfirmView:
    async def test_filled_anketa_is_shown_with_confirm_and_edit_buttons_before_admins(self, dp, bot, session):
        await fill_form(dp, bot, U, ANSWERS, confirm=False)
        last = session.sent_to(U)[-1]
        assert last.text.startswith(texts.ANKETA_CONFIRM.split("\n")[0])
        assert "Aziz Karimov" in last.text and buttons(last) == [CONFIRM, texts.PROFILE_EDIT_BUTTON]
        assert (await state_of(dp, bot, U))[0] == "Form:confirm"
        assert await dbm.get_active_application(U, G) is None and not session.sent_to(tf.ADMIN_ID)

    async def test_confirm_with_clean_anketa_creates_application(self, dp, bot, session, review_ai):
        await at_confirm(dp, bot, session)
        await say(dp, bot, CONFIRM)
        assert len(review_ai.calls) == 1
        assert await dbm.get_active_application(U, G) is not None and len(session.sent_to(tf.ADMIN_ID)) == 1
        assert session.texts_to(U)[-1] == texts.THANKS

    async def test_other_text_asks_to_use_buttons(self, dp, bot, session):
        await at_confirm(dp, bot, session)
        await say(dp, bot, "salom")
        assert session.texts_to(U) == [texts.PROFILE_USE_BUTTONS]
        assert (await state_of(dp, bot, U))[0] == "Form:confirm"

    async def test_ai_down_or_garbled_keeps_the_anketa_until_it_is_checked(self, dp, bot, session, review_ai):
        """AI tekshira olmasa anketa adminga o'tmaydi: saqlanib turadi, keyinroq qayta tasdiqlanadi."""
        await at_confirm(dp, bot, session)
        for answer in (AIError("503"), "bu JSON emas"):
            session.clear()
            review_ai.answer = answer
            await say(dp, bot, CONFIRM)
            last = session.sent_to(U)[-1]
            assert last.text == texts.ANKETA_REVIEW_UNAVAILABLE and buttons(last)[0] == CONFIRM, answer
            assert (await state_of(dp, bot, U))[0] == "Form:confirm"
            assert await dbm.get_active_application(U, G) is None and not session.sent_to(tf.ADMIN_ID)
        review_ai.answer = '{"problems": []}'  # AI qaytdi: qayta bosilgan tugma arizani yuboradi
        await say(dp, bot, CONFIRM)
        assert await dbm.get_active_application(U, G) is not None


class TestAiFindsProblems:
    async def test_bad_fields_are_explained_and_refilled_one_by_one_then_rechecked(self, dp, bot, session, review_ai):
        review_ai.answer = (
            '{"problems": [{"field": "job", "reason": "Kasb <b>tushunarsiz</b>"}, {"field": "about", "reason": ""}]}'
        )
        await at_confirm(dp, bot, session)
        await say(dp, bot, CONFIRM)
        notice, question = session.texts_to(U)
        assert FIELD_LABELS["job"] in notice and "Kasb &lt;b&gt;tushunarsiz&lt;/b&gt;" in notice  # AI matni xavfsiz
        assert FIELD_LABELS["about"] in notice and question == texts.ASK_JOB
        assert await dbm.get_active_application(U, G) is None and not session.sent_to(tf.ADMIN_ID)

        await say(dp, bot, "Backend dasturchi")
        assert session.texts_to(U)[-1] == texts.ASK_ABOUT  # navbatdagi muammoli maydon
        review_ai.answer = '{"problems": []}'
        await say(dp, bot, "Python bilan ishlayman")
        last = session.sent_to(U)[-1]
        assert "Backend dasturchi" in last.text and buttons(last) == [CONFIRM, texts.PROFILE_EDIT_BUTTON]
        assert await dbm.get_profile(U) is None  # yangi anketa faqat ariza yaratilganda saqlanadi

        await say(dp, bot, CONFIRM)  # tasdiqlangach yana tekshiriladi
        assert len(review_ai.calls) == 2
        app = await dbm.get_active_application(U, G)
        assert app is not None and "Backend dasturchi" in app["anketa"]

    async def test_unknown_fields_and_duplicates_are_ignored(self):
        answer = 'Mana: {"problems": [{"field": "age"}, {"field": "job", "reason": "a"}, {"field": "job", "reason": "b"}]}'
        assert _parse(answer) == {"job": "a"}

    async def test_answers_are_wrapped_as_untrusted_data(self, dp, bot, session, review_ai):
        await at_confirm(dp, bot, session)
        await say(dp, bot, CONFIRM)
        system, user = review_ai.calls[0][0]["content"], review_ai.calls[0][1]["content"]
        assert "untrusted" in system and user.startswith("<<<\n") and user.endswith("\n>>>")


class TestLocalCheck:
    async def test_profanity_and_adult_words_are_refilled_without_ai_even_when_ai_is_down(
        self, dp, bot, session, review_ai
    ):
        review_ai.answer = AIError("503")
        answers = [*ANSWERS[:3], "porno aktyorman", ANSWERS[4], "seks videolarni tashamoqchiman"]
        await fill_form(dp, bot, U, answers, confirm=False)
        session.clear()
        await say(dp, bot, CONFIRM)
        notice, question = session.texts_to(U)
        assert FIELD_LABELS["job"] in notice and FIELD_LABELS["join_group"] in notice
        assert FIELD_LABELS["about"] not in notice and question == texts.ASK_JOB
        assert not review_ai.calls and await dbm.get_active_application(U, G) is None  # AI chaqirilmadi
        await say(dp, bot, "Backend dasturchi")
        assert session.texts_to(U)[-1] == texts.ASK_REASON
        await say(dp, bot, "Bilim almashish uchun")
        await say(dp, bot, CONFIRM)  # mahalliy tekshiruv toza: endi AI tekshiradi, u ishlamasa anketa kutadi
        assert len(review_ai.calls) == 1 and session.texts_to(U)[-1] == texts.ANKETA_REVIEW_UNAVAILABLE
        assert await dbm.get_active_application(U, G) is None


class TestEditBeforeConfirm:
    async def test_edit_uses_the_field_menu_and_returns_to_confirm_view(self, dp, bot, session):
        await at_confirm(dp, bot, session)
        await say(dp, bot, texts.PROFILE_EDIT_BUTTON)
        assert session.texts_to(U)[-1] == texts.PROFILE_PICK_FIELD
        await say(dp, bot, FIELD_LABELS["job"])
        assert session.texts_to(U)[-1] == texts.ASK_JOB
        await say(dp, bot, "Frontend dasturchi")
        last = session.sent_to(U)[-1]
        assert "Frontend dasturchi" in last.text and buttons(last) == [CONFIRM, texts.PROFILE_EDIT_BUTTON]
        assert texts.PROFILE_SAVED not in session.texts_to(U) and await dbm.get_profile(U) is None

    async def test_back_from_field_menu_shows_confirm_view(self, dp, bot, session):
        await at_confirm(dp, bot, session)
        await say(dp, bot, texts.PROFILE_EDIT_BUTTON)
        await say(dp, bot, texts.PROFILE_BACK_BUTTON)
        assert (await state_of(dp, bot, U))[0] == "Form:confirm"


class TestSavedProfile:
    async def test_keep_button_is_checked_by_ai_too(self, dp, bot, session, review_ai):
        first = await start_application(dp, bot)
        await dbm.change_status(first, "pending", "accepted")  # chiqib ketib, qayta qo'shilmoqda
        await feed(dp, bot, tf.join_request(U))
        review_ai.answer = '{"problems": [{"field": "about", "reason": "Juda qisqa emas, lekin nomaqbul"}]}'
        session.clear()
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        assert session.texts_to(U)[-1] == texts.ASK_ABOUT and not session.sent_to(G)  # ovozga qo'yilmadi
        review_ai.answer = '{"problems": []}'
        await say(dp, bot, "Toza matn")
        assert (await state_of(dp, bot, U))[0] == "Form:review"
        assert (await dbm.get_profile(U))["about"] == "Toza matn"
        review_ai.answer = AIError("503")  # AI ishlamasa saqlangan anketa ham ovozga qo'yilmaydi
        session.clear()
        await say(dp, bot, texts.PROFILE_KEEP_BUTTON)
        last = session.sent_to(U)[-1]
        assert last.text == texts.ANKETA_REVIEW_UNAVAILABLE and texts.PROFILE_KEEP_BUTTON in buttons(last)
        assert not session.sent_to(G) and (await state_of(dp, bot, U))[0] == "Form:review"


class TestExpiry:
    async def test_expired_unconfirmed_anketa_restarts_from_the_first_question(self, dp, bot, session):
        await at_confirm(dp, bot, session)
        d = await dbm.get_db()
        await d.execute("UPDATE fsm SET updated_at = updated_at - ?", (100 * 3600,))
        await d.commit()
        await say(dp, bot, CONFIRM)
        assert session.texts_to(U) == [texts.FORM_EXPIRED, texts.ASK_FULL_NAME]
        assert await dbm.get_active_application(U, G) is None
