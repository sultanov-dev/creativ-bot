"""handlers/group.py: faqat ADMIN_IDS buyruqlari, /finish, /kick_deleted, a'zolarni kuzatish."""
import datetime as dt
import time
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import (
    BanChatMember, EditMessageText, GetChatMember, GetMe, RestrictChatMember, SendMessage, SetMyCommands, UnbanChatMember,
)
from aiogram.types import ChatPermissions, Message, Update

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.flow import admin_accept, assert_no_errors, cast, feed, get_app, start_application, status_of
from tests.telegram_fakes import FakeSession

A = tf.ADMIN_ID


G = tf.GROUP_ID
VICTIM = 777
ALL_COMMANDS = ["/ban", "/unban", "/mute", "/unmute", "/stats", "/finish", "/kick_deleted"]


def reply_to(user_id: int = VICTIM, message_id: int = 4321) -> Message:
    return tf.group_message_obj(user_id, "spam", message_id=message_id)


async def cmd(dp: Dispatcher, bot: Bot, text: str, *, user: int = A, reply: Message | None = None) -> None:
    await feed(dp, bot, tf.group_message(user, text, reply_to=reply))


def api_calls(session: FakeSession) -> list:
    """Bot API so'rovlari (bot haqida ma'lumot olish GetMe hisobga olinmaydi)."""
    return [r for r in session.requests if not isinstance(r, GetMe)]


def replies(session: FakeSession) -> list[str]:
    return session.texts_to(G)


def edits_text(session: FakeSession) -> str:
    return "\n".join(m.text for m in session.of(EditMessageText) if m.text)


class TestAccessControl:
    async def test_non_admin_slash_message_is_ignored_and_deleted_in_15_seconds(self, dp, bot, session):
        commands = ALL_COMMANDS + ["/", "/qwerty", "/start", "/ban@" + tf.BOT_USERNAME, "/ ban"]
        for message_id, command in enumerate(commands, start=600):
            before = int(time.time())
            await feed(dp, bot, tf.group_message(555, command, message_id=message_id, reply_to=reply_to()))
            assert not api_calls(session), command  # bot javob bermaydi, hech narsa qilmaydi
            rows = [r for r in await dbm.get_pending_deletes() if r["message_id"] == message_id]
            assert len(rows) == 1 and 14 <= rows[0]["delete_at"] - before <= 16, command

    async def test_delete_delay_is_fixed_not_from_auto_delete_setting(self, dp, bot, session, monkeypatch):
        import utils.autodelete as autodelete

        monkeypatch.setattr(autodelete, "AUTO_DELETE_SECONDS", 0)  # umumiy avto-o'chirish o'chiq bo'lsa ham
        await feed(dp, bot, tf.group_message(555, "/qwerty", message_id=601))
        assert [r["message_id"] for r in await dbm.get_pending_deletes()] == [601]

    async def test_telegram_group_admin_who_is_not_bot_admin_is_treated_as_stranger(self, dp, bot, session):
        session.statuses[(G, 555)] = "administrator"
        await feed(dp, bot, tf.group_message(555, "/ban", message_id=602, reply_to=reply_to()))
        assert not session.of(BanChatMember) and not api_calls(session)
        assert [r["message_id"] for r in await dbm.get_pending_deletes()] == [602]

    async def test_other_bots_commands_and_plain_text_are_untouched(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(555, "/rules@some_other_bot", message_id=603))
        await feed(dp, bot, tf.group_message(555, "salom / dunyo", message_id=604))
        await feed(dp, bot, tf.group_message(555, "yo'l /usr/bin", message_id=605))
        assert await dbm.get_pending_deletes() == [] and not api_calls(session)

    async def test_bot_admin_unknown_slash_message_is_not_deleted_by_strangers_rule(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(A, "/qwerty", message_id=606))
        assert await dbm.get_pending_deletes() == []

    async def test_telegram_admin_private_chat_and_missing_sender_are_not_handled(self, dp, bot, session):
        session.statuses[(G, 555)] = "administrator"  # Telegram admini bot admini emas
        await cmd(dp, bot, "/ban", user=555, reply=reply_to())
        await feed(dp, bot, tf.private_message(A, "/stats"))  # shaxsiy chatda guruh buyruqlari yo'q
        raw = tf.group_message(A, "/stats").model_dump(mode="json", by_alias=True, exclude_none=True)
        del raw["message"]["from"]
        await dp.feed_raw_update(bot, raw)
        assert not session.of(BanChatMember) and not session.of(SendMessage)

    async def test_other_bot_mention_is_ignored_own_is_accepted(self, dp, bot, session):
        await cmd(dp, bot, "/stats@some_other_bot")
        assert not session.of(SendMessage)
        await cmd(dp, bot, "/stats@some_other_bot", user=555)  # boshqa botning buyrug'iga tegilmaydi
        assert not session.of(SendMessage) and await dbm.get_pending_deletes() == []
        session.member_count = 1234
        await cmd(dp, bot, f"/stats@{tf.BOT_USERNAME}")
        assert "1234" in replies(session)[0]


class TestBan:
    async def test_ban_target(self, dp, bot, session):
        for args, reply_user, expected in [
            ("", VICTIM, VICTIM),          # javob bo'yicha
            (" 888", None, 888),           # ID bo'yicha
            (" -100123", None, -100123),   # manfiy ID
            (" 888", VICTIM, VICTIM),      # javob argumentdan ustun
        ]:
            session.clear()
            await cmd(dp, bot, "/ban" + args, reply=reply_to(reply_user) if reply_user else None)
            assert [(m.chat_id, m.user_id) for m in session.of(BanChatMember)] == [(G, expected)], args
        assert not session.of(UnbanChatMember)  # blok qoladi
        assert "bloklandi" in replies(session)[0]

    async def test_missing_or_invalid_target_shows_usage(self, dp, bot, session):
        # " --5": ValueError bilan yiqilmasligi kerak
        for text in ["/ban", "/ban abc", "/ban 12abc", "/ban ²", "/ban 1.5", "/ban --5", "/unban"]:
            await cmd(dp, bot, text)
        assert not session.of(BanChatMember) and not session.of(UnbanChatMember)
        assert not any("ValueError" in t for t in session.texts_to(tf.DEVELOPER_ID)), "handler ValueError bilan yiqildi"
        assert "ID yozing" in replies(session)[0]

    @pytest.mark.parametrize("command,method,args,reply_user,status", [
        (c, m, a, r, st)
        for c, m in [("/ban", BanChatMember), ("/mute", RestrictChatMember)]
        for a, r, st in [("", tf.ADMIN2_ID, None), *([(f" {A}", None, None)] if c == "/ban" else [])]  # bot adminlari
    ])
    async def test_cannot_touch_admins(self, dp, bot, session, command, method, args, reply_user, status):
        if status:
            session.statuses[(G, VICTIM)] = status
        await cmd(dp, bot, command + args, reply=reply_to(reply_user) if reply_user else None)
        assert not session.of(method)

    async def test_telegram_group_admin_is_not_special_for_the_bot(self, dp, bot, session):
        for status in ("administrator", "creator"):
            for command, method in [("/ban", BanChatMember), ("/mute", RestrictChatMember)]:
                session.clear()
                session.statuses[(G, VICTIM)] = status  # faqat ADMIN_IDS himoyalanadi; qolganini Telegram hal qiladi
                await cmd(dp, bot, command, reply=reply_to())
                assert session.of(method), (status, command)

    async def test_flood_limit_is_retried_once(self, dp, bot, session, monkeypatch):
        import handlers.group as group

        async def no_sleep(_: float) -> None:
            return None

        monkeypatch.setattr(group.asyncio, "sleep", no_sleep)
        calls: list[Any] = []

        def flaky(m: BanChatMember) -> TelegramRetryAfter | None:
            calls.append(m)
            return TelegramRetryAfter(method=m, message="flood", retry_after=1) if len(calls) == 1 else None

        session.errors[BanChatMember] = flaky
        await cmd(dp, bot, "/ban", reply=reply_to())
        assert len(calls) == 2 and "bloklandi" in replies(session)[0]


    async def test_unban_by_reply_and_id(self, dp, bot, session):
        await cmd(dp, bot, "/unban", reply=reply_to())
        await cmd(dp, bot, "/unban 999")
        calls = session.of(UnbanChatMember)
        assert [c.user_id for c in calls] == [VICTIM, 999] and all(c.only_if_banned for c in calls)


class TestMute:
    async def test_minutes_argument(self, dp, bot, session):
        for arg, expected in [
            ("5", 5), ("0", 1), ("99999999999999999999", 366 * 24 * 60),  # chegaralanadi
            ("", 60), ("abc", 60), ("-5", 60), ("2.5", 60), ("²", 60),     # yo'q yoki noto'g'ri qiymat: standart
        ]:
            session.clear()
            await cmd(dp, bot, f"/mute {arg}", reply=reply_to())
            m = session.of(RestrictChatMember)[0]
            assert m.permissions.can_send_messages is False and m.user_id == VICTIM and m.until_date is not None
            assert abs((m.until_date - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60 - expected) <= 1, arg
        assert f"{expected} daqiqaga" in replies(session)[0]

    async def test_requires_reply(self, dp, bot, session):
        for command in ("/mute 5", "/unmute"):
            session.clear()
            await cmd(dp, bot, command)
            assert not session.of(RestrictChatMember) and "javob bering" in replies(session)[0], command

    async def test_victim_name_is_escaped(self, dp, bot, session):
        await cmd(dp, bot, "/mute", reply=tf.group_message_obj(VICTIM, "x", first_name="<b>Z</b>"))
        assert "<b>Z</b>" not in replies(session)[0] and "&lt;b&gt;Z" in replies(session)[0]

    async def test_unmute_restores_chat_default_permissions(self, dp, bot, session):
        await cmd(dp, bot, "/unmute", reply=reply_to())
        m = session.of(RestrictChatMember)[0]
        assert m.permissions.can_send_messages is True and m.user_id == VICTIM
        assert "jimlikdan chiqarildi" in replies(session)[0]


class TestCommandFailures:
    async def test_failure_is_reported(self, dp, bot, session):
        for command, method, error, text in [
            ("/ban", BanChatMember, tf.bad_request("Bad Request: not enough rights"), "yetarli huquq"),
            ("/unban 5", UnbanChatMember, tf.forbidden(), "blokdan chiqarib bo'lmadi"),
            ("/mute", RestrictChatMember, tf.bad_request(), "jim qilib bo'lmadi"),
            ("/unmute", RestrictChatMember, tf.bad_request(), "bo'lmadi"),
        ]:
            session.clear()
            session.errors = {method: error}
            await cmd(dp, bot, command, reply=reply_to())
            assert text in replies(session)[0], command


class TestKickDeleted:
    async def test_kicks_only_deleted_accounts_and_untracks_them(self, dp, bot, session):
        for uid in (1, 2, 3):
            await dbm.add_member(G, uid)
        session.names[2] = "Deleted Account"
        await cmd(dp, bot, "/kick_deleted")
        assert [m.user_id for m in session.of(BanChatMember)] == [2]
        assert [m.user_id for m in session.of(UnbanChatMember)] == [2]  # chiqariladi, bloklanmaydi
        assert 2 not in await dbm.get_members(G) and {1, 3} <= set(await dbm.get_members(G))
        assert "o'chirilgan akkaunt chiqarildi: 1" in edits_text(session)

    @pytest.mark.parametrize("mode", ["left", "not_found"])
    async def test_gone_members_are_dropped_from_tracking(self, dp, bot, session, mode):
        await dbm.add_member(G, 5)
        if mode == "left":
            session.statuses[(G, 5)] = "left"
        else:
            session.errors[GetChatMember] = lambda m: tf.bad_request("Bad Request: user not found", m) \
                if m.user_id == 5 else None
        await cmd(dp, bot, "/kick_deleted")
        assert 5 not in await dbm.get_members(G) and not session.of(BanChatMember)

    async def test_failures_are_counted_loop_continues_and_failed_members_stay_tracked(self, dp, bot, session):
        for uid in (1, 2, 5):
            await dbm.add_member(G, uid)
        session.names[1] = session.names[2] = "Deleted Account"
        session.errors[BanChatMember] = lambda m: tf.bad_request(method=m) if m.user_id == 1 else None  # ban xatosi
        session.errors[GetChatMember] = lambda m: tf.forbidden(m) if m.user_id == 5 else None  # tekshirib bo'lmadi
        await cmd(dp, bot, "/kick_deleted")
        assert "chiqarildi: 1" in edits_text(session) and "xato: 2" in edits_text(session)
        assert {1, 5} <= set(await dbm.get_members(G)) and 2 not in await dbm.get_members(G)

    async def test_other_groups_and_lookalike_names_are_untouched(self, dp, bot, session):
        await dbm.add_member(G - 1, 9)
        session.names[9] = "Deleted Account"
        await dbm.add_member(G, 1)
        session.names[1] = "deleted account"  # boshqa yozilish: haqiqiy foydalanuvchi bo'lishi mumkin
        await cmd(dp, bot, "/kick_deleted")
        assert not session.of(BanChatMember) and await dbm.get_members(G - 1) == [9]

    async def test_empty_group(self, dp, bot, session):
        await cmd(dp, bot, "/kick_deleted")
        # buyruq bergan adminning o'zi ham kuzatuvdagi a'zo (middleware yozib qo'ygan)
        assert "Tekshirildi: 1" in edits_text(session) and "chiqarildi: 0" in edits_text(session)


class TestFinish:
    async def _voting(self, dp, bot, user: int = 1) -> tuple[int, int]:
        app_id = await start_application(dp, bot, user_id=user)
        await admin_accept(dp, bot, app_id)
        app = await get_app(app_id)
        bot.session.clear()
        return app_id, app["vote_message_id"]

    @pytest.mark.parametrize("reply_id,text", [(None, "javob bergan holda"), (1, "ovoz berish xabari emas")])
    async def test_needs_a_vote_message_reply(self, dp, bot, session, reply_id, text):
        app_id, _ = await self._voting(dp, bot)
        await cmd(dp, bot, "/finish", reply=reply_to(555, reply_id) if reply_id else None)
        assert text in replies(session)[0]
        assert await status_of(app_id) == "voting"

    async def test_finishes_only_that_application(self, dp, bot, session):
        a, msg_a = await self._voting(dp, bot, user=1)
        b, _ = await self._voting(dp, bot, user=2)
        await cast(dp, bot, 200, "yes", a)
        session.clear()
        await cmd(dp, bot, "/finish", reply=reply_to(555, msg_a))
        assert await status_of(a) == "accepted" and await status_of(b) == "voting"

    @pytest.mark.parametrize("votes,status,admin_texts", [
        (["yes"], "accepted", ["✅ <b>Aziz Karimov</b> guruhga qabul qilindi"]),
        ([], "expired", ["❌ <b>Aziz Karimov</b> guruhga qabul qilinmadi: hech kim ovoz bermadi"]),
        (["yes", "no"], "admin_decision", None),  # faqat qaror tugmali hisobot
    ])
    async def test_finish_gives_admin_only_status_or_decision_report(self, dp, bot, session, votes, status, admin_texts):
        app_id, msg = await self._voting(dp, bot)
        for i, v in enumerate(votes):
            await cast(dp, bot, 200 + i, v, app_id)
        session.clear()
        await cmd(dp, bot, "/finish", reply=reply_to(555, msg))
        assert await status_of(app_id) == status
        if admin_texts is None:
            dm = session.sent_to(A)
            assert len(dm) == 1 and dm[0].reply_markup is not None
            assert not any("🏁" in t or "Ovoz berish yakunlandi" in t for t in session.texts_to(A))
        else:
            assert session.texts_to(A) == admin_texts
        if votes:
            assert replies(session) == ["🏁 Ovoz berish yakunlandi."]

    async def test_second_finish_says_already_finished(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        await cast(dp, bot, 200, "yes", app_id)
        await cmd(dp, bot, "/finish", reply=reply_to(555, msg))
        session.clear()
        await cmd(dp, bot, "/finish", reply=reply_to(555, msg))
        # xabar o'chirilgan bo'lsa ham baza yozuvi bor: "yakunlangan" deyiladi
        assert "allaqachon yakunlangan" in replies(session)[0]

    async def test_vote_message_from_other_group_does_not_match(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        other = tf.group_message(A, "/finish", chat_id=G - 1,
                                 reply_to=tf.group_message_obj(555, "v", chat_id=G - 1, message_id=msg))
        await feed(dp, bot, other)
        assert await status_of(app_id) == "voting"


class TestCommandCleanup:
    async def test_handled_admin_command_and_bot_reply_are_queued_for_deletion(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(A, "/stats", message_id=555))
        rows = await dbm.get_pending_deletes()
        assert any(r["chat_id"] == G and r["message_id"] == 555 for r in rows)
        assert session.of(SendMessage)  # javob ham yuborilgan (navbat middleware'i main.py da ulanadi)

    @pytest.mark.parametrize("text", ["/stats@some_other_bot", "salom"])  # boshqa botga yo'naltirilgan buyruq va oddiy matn
    async def test_foreign_text_and_commands_are_not_touched(self, dp, bot, session, text):
        await feed(dp, bot, tf.group_message(555, text, message_id=601))
        assert all(r["message_id"] != 601 for r in await dbm.get_pending_deletes())


def chat_member_update(kind: str, user: dict[str, Any], status: str, *, actor: int = 1, **extra: Any) -> Update:
    """`chat_member` / `my_chat_member` update'i: `user` "left" holatdan `status` ga o'tadi."""
    return Update.model_validate({"update_id": 1, kind: {
        "chat": {"id": G, "type": "supergroup", "title": "G"},
        "from": {"id": actor, "is_bot": False, "first_name": "A"},
        "date": 1700000000,
        "old_chat_member": {"status": "left", "user": user},
        "new_chat_member": {"status": status, "user": user, **extra},
    }})


def member_update(user_id: int, status: str, is_bot: bool = False, **extra: Any) -> Update:
    return chat_member_update("chat_member", {"id": user_id, "is_bot": is_bot, "first_name": "U"}, status, **extra)


RESTRICTED = {"until_date": 0, **dict.fromkeys(ChatPermissions.model_fields, False)}  # ChatMemberRestricted huquqlari


class TestMemberTracking:
    async def test_group_messages_track_senders_but_not_bots_or_private(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(5, "salom"))
        assert await dbm.get_members(G) == [5]
        raw = tf.group_message(6, "salom").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"]["from"]["is_bot"] = True
        await dp.feed_raw_update(bot, raw)
        await feed(dp, bot, tf.private_message(7, "salom"))
        assert await dbm.get_members(G) == [5] and await dbm.get_known_group_ids() == [G]

    async def test_new_and_left_members_via_service_messages(self, dp, bot, session):
        raw = tf.group_message(5, "x").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"].pop("text")
        raw["message"]["new_chat_members"] = [{"id": 8, "is_bot": False, "first_name": "N"},
                                              {"id": 9, "is_bot": True, "first_name": "B"}]
        await dp.feed_raw_update(bot, raw)
        assert sorted(await dbm.get_members(G)) == [5, 8]
        raw["message"].pop("new_chat_members")
        raw["message"]["left_chat_member"] = {"id": 8, "is_bot": False, "first_name": "N"}
        await dp.feed_raw_update(bot, raw)
        assert await dbm.get_members(G) == [5]

    @pytest.mark.parametrize("status,is_bot,extra,tracked_before,expected", [
        ("member", False, {}, False, [11]),            # qo'shildi
        ("left", False, {}, True, []),                 # chiqdi
        ("kicked", False, {"until_date": 0}, True, []),  # haydaldi
        ("member", True, {}, False, []),               # botlar kuzatilmaydi
        ("restricted", False, {"is_member": True, **RESTRICTED}, False, [11]),   # cheklangan, lekin guruhda
        ("restricted", False, {"is_member": False, **RESTRICTED}, True, []),     # cheklangan va chiqib ketgan
    ])
    async def test_chat_member_updates(self, dp, bot, session, status, is_bot, extra, tracked_before, expected):
        if tracked_before:
            await dbm.add_member(G, 11)
        await feed(dp, bot, member_update(11, status, is_bot, **extra))
        assert await dbm.get_members(G) == expected


class TestBotAddedToGroup:
    def _my_chat_member(self, status: str) -> Update:
        me = {"id": tf.BOT_ID, "is_bot": True, "first_name": "Bot", "username": tf.BOT_USERNAME}
        return chat_member_update("my_chat_member", me, status, actor=A)

    async def test_removing_bot_sets_nothing(self, dp, bot, session):
        await feed(dp, bot, self._my_chat_member("left"))
        assert not session.of(SetMyCommands)

    async def test_menu_failure_for_one_admin_does_not_stop_the_other(self, dp, bot, session):
        session.errors[SetMyCommands] = lambda m: tf.bad_request("Bad Request: user not found", m) \
            if m.scope.user_id == tf.ADMIN_ID else None
        await feed(dp, bot, self._my_chat_member("member"))
        assert len(session.of(SetMyCommands)) == 2
        assert_no_errors(session)
