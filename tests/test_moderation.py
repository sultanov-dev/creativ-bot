"""utils/moderation.py (faqat kod) va uning anketa/sabab oqimlariga ulanishi."""

import pytest
from aiogram import Bot, Dispatcher

import database as dbm
import texts
from states import Form
from tests import telegram_fakes as tf
from tests.flow import ANSWERS, feed, start_application, state_of
from utils import moderation
from utils.profanity import has_adult_content, has_profanity, normalize
from tests.table import acheck, same

U = 1


class TestIsAbusive:
    async def test_local_only_no_ai(self):
        """👎 sababi faqat kod bilan tekshiriladi: so'kinish rad etiladi, qolgani o'tadi, AI chaqirilmaydi."""
        assert not hasattr(moderation, "ask_ai")
        await acheck(moderation.is_abusive, [
            ("nega ... siktir, sizga nima", True), ("блять", True), ("f u c k", True),
            ("Tajribasi kam ko'rinadi", False), ("   ", False), ("", False), ("x" * 10_000, False),
        ])


@pytest.fixture
def block(monkeypatch):
    """Anketa (mahalliy filtr) va sabab (AI moderatsiya) oqimlarida "SOKINISH" so'zi bor matnlar rad etiladi."""

    async def fake(text):
        return "SOKINISH" in text

    monkeypatch.setattr("handlers.anketa.has_profanity", lambda text: "SOKINISH" in text)
    monkeypatch.setattr("handlers.reason.is_abusive", fake)


async def at(dp: Dispatcher, bot: Bot, step: int) -> None:
    await feed(dp, bot, tf.join_request(U))
    for a in ANSWERS[:step]:
        await feed(dp, bot, tf.private_message(U, a))


class TestAnketaChecksFreeText:
    @pytest.mark.parametrize("step,state", [
        (0, Form.full_name), (3, Form.job), (4, Form.about), (5, Form.join_group),
    ])
    async def test_abusive_text_is_refused_then_clean_retry_advances(self, dp, bot, session, block, step, state):
        await at(dp, bot, step)
        session.clear()
        await feed(dp, bot, tf.private_message(U, "SOKINISH Karimov" if step == 0 else "SOKINISH"))
        assert session.texts_to(U) == [texts.MODERATION_WARNING]
        assert (await state_of(dp, bot, U))[0] == state.state
        assert await dbm.get_active_application(U, tf.GROUP_ID) is None and await dbm.get_profile(U) is None
        await feed(dp, bot, tf.private_message(U, "Toza Matn"))  # toza matn bilan qayta urinish o'tadi
        assert (await state_of(dp, bot, U))[0] != state.state

    async def test_answers_are_not_sent_to_ai_one_by_one(self, dp, bot, session, monkeypatch, review_ai):
        await start_application(dp, bot, answers=["Aziz Karimov", "+998901234567", "25", "Dasturchi", "Haqida", "Sabab"])
        assert len(review_ai.calls) == 1  # faqat tasdiqlangandan keyin, butun anketa bir marta
        sent = review_ai.calls[0][1]["content"]
        assert "Aziz Karimov" in sent and "Sabab" in sent
        assert "+998901234567" not in sent and "25" not in sent  # telefon va yosh AI'ga bormaydi

    async def test_edit_mode_also_checks_text(self, dp, bot, session, block):
        first = await start_application(dp, bot)
        await dbm.change_status(first, "pending", "accepted")
        await feed(dp, bot, tf.join_request(U))
        await feed(dp, bot, tf.private_message(U, texts.PROFILE_EDIT_BUTTON))
        from keyboards.profile import FIELD_LABELS
        await feed(dp, bot, tf.private_message(U, FIELD_LABELS["job"]))
        session.clear()
        await feed(dp, bot, tf.private_message(U, "SOKINISH"))
        assert session.texts_to(U) == [texts.MODERATION_WARNING]
        profile = await dbm.get_profile(U)
        assert profile is not None and profile["job"] == "Dasturchi"  # eski qiymat saqlanib qoldi


class TestLocalProfanityFilter:
    def test_profanity_is_caught(self):
        same(has_profanity, [
            *"fuck you|f*ck|fuuuck|FUCK|f u c k|motherfucker|shit|bitch|asshole".split("|"),
            *"блять|БЛЯДЬ|хуй|хуйня|пизда|сука|ебать".split("|"),
            *"siktir|Sikaman seni|qo'toq|qotoq|ko'tak|jalab|yeban|dalbayob|gandon|amingni".split("|"),
            "Siz juda qotoq ekansiz", "nega ... siktir", *"om|OM|omm|ом|sen om|nega om!|om, nima".split("|"),
        ], True)

    def test_normal_text_is_not_flagged(self):
        same(has_profanity, [
            *"Aziz Karimov|dasturchi|sikl bilan ishlash|for sikli|harom emas|Nigeria|assistant|class|salom".split("|"),
            *"Python va Django|men 25 yoshdaman|skala|Scunthorpe|analysis|passion|hello|Husan|Xushnud|pedagog".split("|"),
            *"kotib|Kotlin|kot|2024|Men Django bilan ishlayman||   ".split("|"),
            "guruhga qo'shilmoqchiman, chunki o'rganishni xohlayman",
            # "om" faqat butun so'z sifatida belgilanadi: uning ichida/boshida kelgan oddiy so'zlar toza
            *"omad|omon|omborxona|Omar|Omonov|tom|dom|Rom|kompyuter|komil|somsa|omma".split("|"),
        ], False)

    def test_adult_words(self):
        same(has_adult_content, [
            "porno aktyorman", "seks videolarni tashamoqchiman", "PORNO", "порно", "секс", "s e x",
            "pornografiya", "erotik video", "xentai", "hentai", "onlyfans", "Intim xizmat", "sexy", "eskort",
        ], True)
        same(has_adult_content, [
            "Aziz Karimov", "dasturchi", "sport seksiyasi", "seksiya", "Essex", "Sussex", "sekretar", "sexta",
            "Python va Django", "intellekt", "minimal", "", None,
        ], False)

    def test_normalize_handles_cyrillic_leet_and_repeats(self):
        assert normalize("БЛЯДЬ") == "blyad" and normalize("Fuuuck") == "fuck"
        assert normalize("f*ck") == "fck"
        assert normalize("2024") == "2024"  # raqamlar o'zgarmaydi

    def test_none_is_safe(self):
        assert has_profanity(None) is False  # pyright: ignore[reportArgumentType]
