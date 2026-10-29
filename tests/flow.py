"""Dispatcher orqali to'liq oqim: update yuboriladi, soxta Telegram sessiyasida natija tekshiriladi."""
from collections.abc import Sequence

from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, DeclineChatJoinRequest, EditMessageText
from aiogram.types import Update

import database as dbm
import texts
from callbacks import ApplicantCB, DecisionCB, VoteCB
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.telegram_fakes import FakeSession
from states import Form
from utils import content_check
from utils.fsm import get_private_state


async def feed(dp: Dispatcher, bot: Bot, update: Update):
    """Update'ni bot kontekstida (message.reply va h.k. ishlashi uchun) haqiqiy yo'l bilan beradi."""
    raw = update.model_dump(mode="json", by_alias=True, exclude_none=True)
    result = await dp.feed_raw_update(bot, raw)
    await content_check.drain()  # fondagi AI tekshiruvi (reklama) ham tugasin: natija aniq bo'lsin
    return result


def last_alert(session: FakeSession) -> AnswerCallbackQuery:
    return session.of(AnswerCallbackQuery)[-1]


def assert_no_errors(session: FakeSession) -> None:
    """Handler yiqilmagan: foydalanuvchiga umumiy xato yoki dasturchiga ogohlantirish ketmagan."""
    for m in session.requests:
        text = getattr(m, "text", None)
        assert text != texts.ERROR_GENERIC, "handler xatosi: foydalanuvchiga ERROR_GENERIC yuborilgan"
        assert getattr(m, "chat_id", None) != tf.DEVELOPER_ID, f"dasturchiga xato yuborilgan: {text}"


ANSWERS = ["Aziz Karimov", texts.SKIP_BUTTON, "25", "Dasturchi", "O'zim haqimda", "Qiziq"]


async def fill_form(
    dp: Dispatcher, bot: Bot, user_id: int = 1, answers: Sequence[str] | None = None, *, group_id: int = tf.GROUP_ID,
    confirm: bool = True,
) -> None:
    """Join request + butun anketa (ariza yaratilishi shart emas: xato yo'llarini sinash uchun).

    Barcha javoblar qabul qilinib anketa ko'rsatilgan bo'lsa (Form.confirm), "Tasdiqlash" ham bosiladi.
    """
    await feed(dp, bot, tf.join_request(user_id, group_id))
    for a in answers or ANSWERS:
        await feed(dp, bot, tf.private_message(user_id, a))
    if confirm and await private_state(dp, bot, user_id) == Form.confirm.state:
        await feed(dp, bot, tf.private_message(user_id, texts.ANKETA_CONFIRM_BUTTON))


async def private_state(dp: Dispatcher, bot: Bot, user_id: int) -> str | None:
    return await get_private_state(storage=dp.storage, bot=bot, user_id=user_id).get_state()


async def start_application(
    dp: Dispatcher, bot: Bot, user_id: int = 1, answers: Sequence[str] | None = None, *, group_id: int = tf.GROUP_ID
) -> int:
    """fill_form + yaratilgan arizaning id'si."""
    await fill_form(dp, bot, user_id, answers, group_id=group_id)
    app = await dbm.get_active_application(user_id, group_id)
    assert app is not None, "anketadan keyin ariza yaratilmagan"
    return app["id"]


def applicant_cb(action, app_id):
    return ApplicantCB(action=action, app_id=app_id).pack()


def decision_cb(action, app_id):
    return DecisionCB(action=action, app_id=app_id).pack()


def vote_cb(vote, app_id):
    return VoteCB(vote=vote, app_id=app_id).pack()


async def admin_accept(dp, bot, app_id, admin=tf.ADMIN_ID):
    await feed(dp, bot, tf.callback(admin, applicant_cb("accept", app_id)))


async def cast(dp, bot, user_id, vote, app_id, *, message_id=None):
    """Ovoz tugmasini bosadi; xabar id'si standart bo'yicha arizaning haqiqiy ovoz xabari id'si."""
    if message_id is None:
        app = await dbm.get_application(app_id)  # noma'lum ariza ham bo'lishi mumkin
        message_id = (app["vote_message_id"] if app else None) or 777
    await feed(dp, bot, tf.callback(user_id, vote_cb(vote, app_id), chat_id=tf.GROUP_ID, message_id=message_id))


async def get_app(app_id: int) -> dict:
    """Mavjud ariza qatori (yo'q bo'lsa test yiqiladi)."""
    app = await dbm.get_application(app_id)
    assert app is not None, f"ariza {app_id} topilmadi"
    return app


async def status_of(app_id: int) -> str:
    return (await get_app(app_id))["status"]


async def state_of(dp: Dispatcher, bot: Bot, user: int = 1) -> tuple[str | None, dict]:
    """Foydalanuvchining shaxsiy chatdagi FSM holati va ma'lumotlari."""
    ctx = dp.fsm.get_context(bot, chat_id=user, user_id=user)
    return await ctx.get_state(), await ctx.get_data()


async def set_full_name(app_id: int, name: str) -> None:
    db = await dbm.get_db()
    await db.execute("UPDATE applications SET full_name = ? WHERE id = ?", (name, app_id))
    await db.commit()


async def make_voting_app(
    user_id: int = 1,
    group_id: int = tf.GROUP_ID,
    vote_message_id: int | None = 500,
    votes: Sequence[str] = (),
    *,
    expired: bool = True,
) -> int:
    """Bazada to'g'ridan-to'g'ri ovoz berish bosqichidagi ariza; voter id'lari 100, 101, ...; standart bo'yicha muddati o'tgan."""
    app_id = await dbm.create_application(user_id, group_id, "Aziz Karimov", "ANKETA\n", phone="+998901234567")
    assert app_id is not None
    await dbm.start_voting(app_id, 10)
    if vote_message_id:
        await dbm.set_vote_message(app_id, vote_message_id)
    for i, v in enumerate(votes):
        await dbm.add_vote(app_id, 100 + i, v)
    if expired:
        await expire_voting(app_id)
    return app_id


def declined(session: FakeSession) -> list[DeclineChatJoinRequest]:
    return session.of(DeclineChatJoinRequest)


def edits(session: FakeSession) -> list[EditMessageText]:
    return session.of(EditMessageText)
