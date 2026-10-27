"""Dispatcher orqali to'liq oqim: update yuboriladi, soxta Telegram sessiyasida natija tekshiriladi."""
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, DeclineChatJoinRequest, EditMessageText
from aiogram.types import Update

import database as dbm
import texts
from callbacks import ApplicantCB, CreatorCB, VoteCB
from tests import telegram_fakes as tf
from tests.telegram_fakes import FakeSession


async def feed(dp: Dispatcher, bot: Bot, update: Update):
    """Update'ni bot kontekstida (message.reply va h.k. ishlashi uchun) haqiqiy yo'l bilan beradi."""
    raw = update.model_dump(mode="json", by_alias=True, exclude_none=True)
    return await dp.feed_raw_update(bot, raw)


def last_alert(session: FakeSession) -> AnswerCallbackQuery:
    return session.of(AnswerCallbackQuery)[-1]


def assert_no_errors(session: FakeSession) -> None:
    """Handler yiqilmagan: foydalanuvchiga umumiy xato yoki dasturchiga ogohlantirish ketmagan."""
    for m in session.requests:
        text = getattr(m, "text", None)
        assert text != texts.ERROR_GENERIC, "handler xatosi: foydalanuvchiga ERROR_GENERIC yuborilgan"
        assert getattr(m, "chat_id", None) != tf.DEVELOPER_ID, f"dasturchiga xato yuborilgan: {text}"


ANSWERS = ["Aziz Karimov", texts.SKIP_BUTTON, "25", "Dasturchi", "O'zim haqimda", "Qiziq"]


async def start_application(dp, bot, user_id=1, answers=None, *, group_id=tf.GROUP_ID):
    """Join request + butun anketa; ariza id'sini qaytaradi (yoki None)."""
    await feed(dp, bot, tf.join_request(user_id, group_id))
    for a in answers or ANSWERS:
        await feed(dp, bot, tf.private_message(user_id, a))
    app = await dbm.get_active_application(user_id, group_id)
    return app["id"] if app else None


def applicant_cb(action, app_id):
    return ApplicantCB(action=action, app_id=app_id).pack()


def creator_cb(action, app_id):
    return CreatorCB(action=action, app_id=app_id).pack()


def vote_cb(vote, app_id):
    return VoteCB(vote=vote, app_id=app_id).pack()


async def admin_accept(dp, bot, app_id, admin=tf.ADMIN_ID):
    await feed(dp, bot, tf.callback(admin, applicant_cb("accept", app_id)))


async def cast(dp, bot, user_id, vote, app_id, *, message_id=None):
    """Ovoz tugmasini bosadi; xabar id'si standart bo'yicha arizaning haqiqiy ovoz xabari id'si."""
    if message_id is None:
        app = await dbm.get_application(app_id)
        message_id = (app or {}).get("vote_message_id") or 777
    await feed(dp, bot, tf.callback(user_id, vote_cb(vote, app_id), chat_id=tf.GROUP_ID, message_id=message_id))


async def status_of(app_id):
    return (await dbm.get_application(app_id))["status"]


def declined(session):
    return session.of(DeclineChatJoinRequest)


def edits(session):
    return session.of(EditMessageText)
