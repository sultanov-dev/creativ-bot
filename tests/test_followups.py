"""Anketa chekka holatlari: tugallanmagan anketa, bot to'xtagan oqim, muddati o'tgan anketa, yetkazilmagan arizani qayta yuborish."""
import asyncio
from typing import Callable

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import DeclineChatJoinRequest, SendMessage

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.flow import ANSWERS, feed, fill_form, get_app, start_application, state_of
from tests.telegram_fakes import FakeSession
from utils.applications import redeliver_undelivered

G = tf.GROUP_ID
U = 1
ADMINS = (tf.ADMIN_ID, tf.ADMIN2_ID)
BEFORE_LAST = ANSWERS[:-1]  # oxirgi savol (join_group) dan oldingi javoblar


async def count_applications() -> int:
    d = await dbm.get_db()
    row = await (await d.execute("SELECT COUNT(*) FROM applications")).fetchone()
    assert row is not None
    return row[0]


async def age_form(hours: float) -> None:
    """Barcha FSM yozuvlarini `hours` soatga eskirtiradi."""
    d = await dbm.get_db()
    await d.execute("UPDATE fsm SET updated_at = updated_at - ?", (int(hours * 3600),))
    await d.commit()


def block_admins(session: FakeSession) -> None:
    session.errors[SendMessage] = lambda m: tf.forbidden(m) if m.chat_id in ADMINS else None


async def crash_last_answer(
    dp: Dispatcher, bot: Bot, monkeypatch: pytest.MonkeyPatch, answers: list[str] | None = None
) -> Callable[[], None]:
    """Oxirgi javobda bot "yiqiladi" (adminlarga yuborish o'rniga xato). Qaytaradi: yiqilishni bekor qiluvchi funksiya."""
    import handlers.anketa as anketa

    await fill_form(dp, bot, U, answers or BEFORE_LAST)
    real = anketa.safe_send

    async def crashing(**kw):
        raise RuntimeError("bot to'xtadi")

    monkeypatch.setattr(anketa, "safe_send", crashing)
    await feed(dp, bot, tf.private_message(U, ANSWERS[-1]))
    return lambda: monkeypatch.setattr(anketa, "safe_send", real)


class TestUnfinishedQuestionnaire:
    async def test_second_join_mid_form_asks_to_finish_and_repeats_question(self, dp, bot, session):
        await feed(dp, bot, tf.join_request(U))
        session.clear()
        await feed(dp, bot, tf.join_request(U))  # birinchi savol ham takrorlanadi
        assert session.texts_to(U) == [texts.FINISH_FORM_FIRST, texts.ASK_FULL_NAME]
        await feed(dp, bot, tf.private_message(U, "Aziz Karimov"))
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert session.texts_to(U) == [texts.FINISH_FORM_FIRST, texts.ASK_PHONE]
        # holat va javoblar saqlanib qoldi: davom ettirish mumkin
        await feed(dp, bot, tf.private_message(U, texts.SKIP_BUTTON))
        assert session.texts_to(U)[-1] == texts.ASK_AGE

    async def test_no_stale_note_after_expired_application(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        await dbm.change_status(app_id, "pending", "expired")
        await fill_form(dp, bot, U, ["Aziz Karimov"])  # eslatma + savol boshlandi
        session.clear()
        await feed(dp, bot, tf.join_request(U))  # yana so'rov: eski "muddati o'tgan" xabari emas
        sent = session.texts_to(U)
        assert texts.REJOIN_AFTER_EXPIRED not in sent and sent[0] == texts.FINISH_FORM_FIRST

    async def test_other_group_still_starts_fresh(self, dp, bot, session):
        await fill_form(dp, bot, U, ["Aziz Karimov"])
        session.clear()
        await feed(dp, bot, tf.join_request(U, chat_id=-1009999))
        assert texts.FINISH_FORM_FIRST not in session.texts_to(U)
        assert session.texts_to(U)[-1] == texts.ASK_FULL_NAME


class TestBotStoppedMidFlow:
    async def test_welcome_cannot_be_sent_state_cleared_and_request_declined(self, dp, bot, session):
        session.errors[SendMessage] = lambda m: tf.forbidden(m) if m.chat_id == U else None
        await feed(dp, bot, tf.join_request(U))
        assert (await state_of(dp, bot, U))[0] is None
        assert [(m.chat_id, m.user_id) for m in session.of(DeclineChatJoinRequest)] == [(G, U)]
        assert not session.sent_to(tf.DEVELOPER_ID)  # dasturchiga xato ketmadi

    async def test_crash_after_application_created_keeps_answers_and_retry_reaches_admins(
        self, dp, bot, session, monkeypatch
    ):
        restore = await crash_last_answer(dp, bot, monkeypatch)
        assert (await state_of(dp, bot, U))[0] == "Form:join_group"  # javoblar yo'qolmadi
        pending = await dbm.get_active_application(U, G)
        assert pending is not None and pending["status"] == "pending"
        assert not session.sent_to(tf.ADMIN_ID)

        restore()
        session.clear()
        await feed(dp, bot, tf.private_message(U, ANSWERS[-1]))  # oxirgi javob qayta ishlanadi (redelivery)
        assert all(len(session.sent_to(a)) == 1 for a in ADMINS)
        assert (await state_of(dp, bot, U))[0] is None
        assert texts.THANKS in session.texts_to(U)
        assert await count_applications() == 1  # dublikat yo'q

    async def test_state_is_cleared_only_after_admins_got_it(self, dp, bot, session):
        app_id = await start_application(dp, bot)
        assert (await state_of(dp, bot, U))[0] is None
        assert len(session.sent_to(tf.ADMIN_ID)) == 1
        assert (await get_app(app_id))["admins_notified"] == 1 and await dbm.get_undelivered_applications() == []
        # tugagan arizadan keyin yangi so'rov "avval anketani tugating" demaydi
        await dbm.change_status(app_id, "pending", "rejected")
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        assert texts.FINISH_FORM_FIRST not in session.texts_to(U)

    async def test_double_tap_on_last_answer_makes_one_application(self, dp, bot, session):
        await fill_form(dp, bot, U, BEFORE_LAST)
        session.clear()
        await asyncio.gather(
            feed(dp, bot, tf.private_message(U, ANSWERS[-1])), feed(dp, bot, tf.private_message(U, ANSWERS[-1]))
        )
        assert len(session.sent_to(tf.ADMIN_ID)) == 1
        assert await count_applications() == 1

    async def test_no_admin_reachable_marks_failed_and_clears_state(self, dp, bot, session):
        await fill_form(dp, bot, U, BEFORE_LAST)
        block_admins(session)
        await feed(dp, bot, tf.private_message(U, ANSWERS[-1]))
        assert await dbm.last_application_status(U, G) == "failed"
        assert (await state_of(dp, bot, U))[0] is None
        assert session.texts_to(U)[-1] == texts.ERROR_GENERIC


class TestExpiredQuestionnaire:
    async def _half_done(self, dp: Dispatcher, bot: Bot) -> None:
        await fill_form(dp, bot, U, ANSWERS[:2])  # ism + telefon (o'tkazib yuborildi)

    async def test_continuing_after_expiry_warns_and_restarts(self, dp, bot, session):
        await self._half_done(dp, bot)
        await age_form(25)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "25"))
        assert session.texts_to(U) == [texts.FORM_EXPIRED, texts.ASK_FULL_NAME]
        state, data = await state_of(dp, bot, U)
        assert state == "Form:full_name" and data.get("group_id") == G and "full_name" not in data
        assert await dbm.get_active_application(U, G) is None
        await feed(dp, bot, tf.private_message(U, "Aziz Karimov"))  # qaytadan to'ldirish ishlaydi
        assert session.texts_to(U)[-1] == texts.ASK_PHONE

    @pytest.mark.parametrize("hours,ttl", [(23, None), (1000, 0)])  # muddat o'tmagan; TTL=0 o'chirilgan
    async def test_not_expired_continues(self, dp, bot, session, monkeypatch, hours, ttl):
        import utils.form_expiry as fe

        if ttl is not None:
            monkeypatch.setattr(fe, "FORM_TTL_HOURS", ttl)
        await self._half_done(dp, bot)
        await age_form(hours)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "25"))
        assert session.texts_to(U) == [texts.ASK_JOB]

    async def test_new_join_request_after_expiry_starts_fresh_not_finish_first(self, dp, bot, session):
        await self._half_done(dp, bot)
        await age_form(30)
        session.clear()
        await feed(dp, bot, tf.join_request(U))
        sent = session.texts_to(U)
        assert texts.FINISH_FORM_FIRST not in sent and sent[-1] == texts.ASK_FULL_NAME
        assert (await state_of(dp, bot, U))[0] == "Form:full_name"

    async def test_expired_saved_profile_review_is_shown_again_with_note(self, dp, bot, session):
        first = await start_application(dp, bot)
        await dbm.change_status(first, "pending", "accepted")
        await feed(dp, bot, tf.join_request(U))
        assert (await state_of(dp, bot, U))[0] == "Form:review"
        await age_form(30)
        session.clear()
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_KEEP_BUTTON))
        sent = session.texts_to(U)
        assert sent[0] == texts.FORM_EXPIRED and "Ism" in sent[1]
        assert await dbm.get_active_application(U, G) is None  # "shunday qoldirish" qayta bosilmaguncha ariza yo'q

    async def test_user_without_form_is_untouched(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(77, "salom"))
        assert texts.FORM_EXPIRED not in session.texts_to(77)


class TestRedeliverUndelivered:
    async def test_complete_application_is_redelivered_once(self, dp, bot, session, monkeypatch):
        answers = ["Aziz Karimov", "+998901234567", "25", "Dasturchi", "Haqida"]
        restore = await crash_last_answer(dp, bot, monkeypatch, answers)
        app = await dbm.get_active_application(U, G)
        assert app is not None and app["admins_notified"] == 0 and not session.sent_to(tf.ADMIN_ID)
        restore()  # soxta safe_send olib tashlanadi
        session.clear()
        assert await redeliver_undelivered(bot, dp.storage) == 1
        for admin in ADMINS:
            msgs = session.sent_to(admin)
            assert len(msgs) == 1 and "Aziz Karimov" in msgs[0].text and "+998901234567" in msgs[0].text
            assert msgs[0].reply_markup is not None
        assert (await get_app(app["id"]))["admins_notified"] == 1
        assert (await state_of(dp, bot, U))[0] is None
        assert session.texts_to(U) == [texts.THANKS]
        session.clear()
        assert await redeliver_undelivered(bot, dp.storage) == 0 and not session.requests

    def test_phone_line_sits_after_name_like_normal_delivery(self):
        from utils.form_anketa import anketa_for_admins, format_anketa

        data = {"full_name": "Aziz Karimov", "phone": "+998901234567", "age": 25, "job": "j", "about": "a", "join_group": "q"}
        assert anketa_for_admins(format_anketa(data), data["phone"]) == format_anketa(data, with_phone=True)
        assert anketa_for_admins("x\ny\n", None) == "x\ny\n"

    async def test_unreachable_admins_mark_failed_and_tell_user(self, dp, bot, session, monkeypatch):
        restore = await crash_last_answer(dp, bot, monkeypatch)
        restore()
        session.clear()
        block_admins(session)
        await redeliver_undelivered(bot, dp.storage)
        app = await dbm.get_active_application(U, G)
        assert app is None and await dbm.last_application_status(U, G) == "failed"
        assert session.texts_to(U) == [texts.ERROR_GENERIC]

    async def test_incomplete_questionnaire_is_never_sent_to_admins(self, dp, bot, session):
        await fill_form(dp, bot, U, ["Aziz Karimov"])
        session.clear()
        assert await redeliver_undelivered(bot, dp.storage) == 0
        assert not session.sent_to(tf.ADMIN_ID) and (await state_of(dp, bot, U))[0] == "Form:phone"
