"""handlers/group.py: faqat ADMIN_IDS buyruqlari, /finish, /kick_deleted, a'zolarni kuzatish."""
import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import (
    BanChatMember,
    EditMessageText,
    GetChatMember,
    RestrictChatMember,
    SendMessage,
    SetMyCommands,
    UnbanChatMember,
)
from aiogram.types import Chat, ChatMemberUpdated, Update

import database as dbm
import texts
from tests import telegram_fakes as tf
from tests.conftest import expire_voting
from tests.flow import admin_accept, assert_no_errors, cast, feed, start_application, status_of

A = tf.ADMIN_ID
G = tf.GROUP_ID
VICTIM = 777


def reply_to(user_id=VICTIM, message_id=4321):
    return tf.group_message_obj(user_id, "spam", message_id=message_id)


async def cmd(dp, bot, text, *, user=A, reply=None):
    await feed(dp, bot, tf.group_message(user, text, reply_to=reply))


def replies(session):
    return session.texts_to(G)


class TestAccessControl:
    @pytest.mark.parametrize("command", ["/ban", "/unban", "/mute", "/unmute", "/stats", "/finish", "/kick_deleted"])
    async def test_non_admins_are_silently_ignored(self, dp, bot, session, command):
        await cmd(dp, bot, command, user=555, reply=reply_to())
        assert session.requests == []

    async def test_telegram_group_admin_is_not_a_bot_admin(self, dp, bot, session):
        session.statuses[(G, 555)] = "administrator"
        await cmd(dp, bot, "/ban", user=555, reply=reply_to())
        assert not session.of(BanChatMember)

    async def test_admin_commands_in_private_chat_are_not_handled(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(A, "/stats"))
        assert not any("a'zolar soni" in t for t in session.texts_to(A))

    async def test_message_without_sender_is_ignored(self, dp, bot, session):
        raw = tf.group_message(A, "/stats").model_dump(mode="json", by_alias=True, exclude_none=True)
        del raw["message"]["from"]
        await dp.feed_raw_update(bot, raw)
        assert not session.of(SendMessage)

    async def test_command_with_other_bot_mention_is_ignored(self, dp, bot, session):
        await cmd(dp, bot, "/stats@some_other_bot")
        assert not session.of(SendMessage)

    async def test_own_bot_mention_is_accepted(self, dp, bot, session):
        await cmd(dp, bot, f"/stats@{tf.BOT_USERNAME}")
        assert "42" in replies(session)[0]


class TestBan:
    async def test_ban_by_reply(self, dp, bot, session):
        await cmd(dp, bot, "/ban", reply=reply_to())
        assert [(m.chat_id, m.user_id) for m in session.of(BanChatMember)] == [(G, VICTIM)]
        assert not session.of(UnbanChatMember)  # blok qoladi
        assert "bloklandi" in replies(session)[0]

    async def test_ban_by_id(self, dp, bot, session):
        await cmd(dp, bot, "/ban 888")
        assert session.of(BanChatMember)[0].user_id == 888

    async def test_ban_by_negative_id(self, dp, bot, session):
        await cmd(dp, bot, "/ban -100123")
        assert session.of(BanChatMember)[0].user_id == -100123

    async def test_reply_wins_over_argument(self, dp, bot, session):
        await cmd(dp, bot, "/ban 888", reply=reply_to())
        assert session.of(BanChatMember)[0].user_id == VICTIM

    @pytest.mark.parametrize("args", ["", " abc", " 12abc", " ²", " 1.5"])
    async def test_ban_without_valid_target_shows_usage(self, dp, bot, session, args):
        await cmd(dp, bot, "/ban" + args)
        assert not session.of(BanChatMember)
        assert "ID yozing" in replies(session)[0]

    async def test_cannot_ban_bot_admin(self, dp, bot, session):
        await cmd(dp, bot, "/ban", reply=reply_to(tf.ADMIN2_ID))
        assert not session.of(BanChatMember) and "adminni bloklab bo'lmaydi" in replies(session)[0]

    @pytest.mark.parametrize("status", ["administrator", "creator"])
    async def test_cannot_ban_telegram_group_admin(self, dp, bot, session, status):
        session.statuses[(G, VICTIM)] = status
        await cmd(dp, bot, "/ban", reply=reply_to())
        assert not session.of(BanChatMember)

    async def test_cannot_ban_self(self, dp, bot, session):
        await cmd(dp, bot, f"/ban {A}")
        assert not session.of(BanChatMember)

    async def test_missing_rights_is_reported(self, dp, bot, session):
        session.errors[BanChatMember] = TelegramBadRequest(method=None, message="Bad Request: not enough rights")
        await cmd(dp, bot, "/ban", reply=reply_to())
        assert "yetarli huquq" in replies(session)[0]

    async def test_flood_limit_is_retried_once(self, dp, bot, session, monkeypatch):
        import handlers.group as group

        async def no_sleep(_):
            return None

        monkeypatch.setattr(group.asyncio, "sleep", no_sleep)
        calls = []

        def flaky(m):
            calls.append(m)
            return TelegramRetryAfter(method=m, message="flood", retry_after=1) if len(calls) == 1 else None

        session.errors[BanChatMember] = flaky
        await cmd(dp, bot, "/ban", reply=reply_to())
        assert len(calls) == 2 and "bloklandi" in replies(session)[0]

    async def test_double_minus_argument_is_a_usage_error_not_a_crash(self, dp, bot, session):
        await cmd(dp, bot, "/ban --5")
        assert not any("ValueError" in t for t in session.texts_to(tf.DEVELOPER_ID)), "handler ValueError bilan yiqildi"
        assert "ID yozing" in replies(session)[0]


class TestUnban:
    async def test_unban_by_reply_and_id(self, dp, bot, session):
        await cmd(dp, bot, "/unban", reply=reply_to())
        await cmd(dp, bot, "/unban 999")
        calls = session.of(UnbanChatMember)
        assert [c.user_id for c in calls] == [VICTIM, 999] and all(c.only_if_banned for c in calls)

    async def test_unban_usage(self, dp, bot, session):
        await cmd(dp, bot, "/unban")
        assert "ID yozing" in replies(session)[0]

    async def test_unban_failure(self, dp, bot, session):
        session.errors[UnbanChatMember] = TelegramForbiddenError(method=None, message="Forbidden")
        await cmd(dp, bot, "/unban 5")
        assert "blokdan chiqarib bo'lmadi" in replies(session)[0]


class TestMute:
    def _minutes(self, session):
        import datetime as dt

        m = session.of(RestrictChatMember)[0]
        return round((m.until_date - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60)

    async def test_default_is_60_minutes(self, dp, bot, session):
        await cmd(dp, bot, "/mute", reply=reply_to())
        m = session.of(RestrictChatMember)[0]
        assert m.permissions.can_send_messages is False and m.user_id == VICTIM
        assert self._minutes(session) in (59, 60)
        assert "60 daqiqaga" in replies(session)[0]

    @pytest.mark.parametrize("arg,expected", [("5", 5), ("0", 1), ("99999999999999999999", 366 * 24 * 60)])
    async def test_minutes_argument_is_clamped(self, dp, bot, session, arg, expected):
        await cmd(dp, bot, f"/mute {arg}", reply=reply_to())
        assert f"{expected} daqiqaga" in replies(session)[0]

    @pytest.mark.parametrize("arg", ["abc", "-5", "2.5", "²"])
    async def test_garbage_argument_falls_back_to_default(self, dp, bot, session, arg):
        await cmd(dp, bot, f"/mute {arg}", reply=reply_to())
        assert "60 daqiqaga" in replies(session)[0]

    async def test_requires_reply(self, dp, bot, session):
        await cmd(dp, bot, "/mute 5")
        assert not session.of(RestrictChatMember) and "javob bering" in replies(session)[0]

    async def test_cannot_mute_admins(self, dp, bot, session):
        await cmd(dp, bot, "/mute", reply=reply_to(tf.ADMIN2_ID))
        session.statuses[(G, VICTIM)] = "administrator"
        await cmd(dp, bot, "/mute", reply=reply_to())
        assert not session.of(RestrictChatMember)

    async def test_victim_name_is_escaped(self, dp, bot, session):
        reply = tf.group_message_obj(VICTIM, "x", first_name="<b>Z</b>")
        await cmd(dp, bot, "/mute", reply=reply)
        assert "<b>Z</b>" not in replies(session)[0] and "&lt;b&gt;Z" in replies(session)[0]

    async def test_failure_is_reported(self, dp, bot, session):
        session.errors[RestrictChatMember] = TelegramBadRequest(method=None, message="Bad Request: x")
        await cmd(dp, bot, "/mute", reply=reply_to())
        assert "jim qilib bo'lmadi" in replies(session)[0]

    async def test_unmute_restores_chat_default_permissions(self, dp, bot, session):
        await cmd(dp, bot, "/unmute", reply=reply_to())
        m = session.of(RestrictChatMember)[0]
        assert m.permissions.can_send_messages is True and m.user_id == VICTIM
        assert "jimlikdan chiqarildi" in replies(session)[0]

    async def test_unmute_requires_reply(self, dp, bot, session):
        await cmd(dp, bot, "/unmute")
        assert not session.of(RestrictChatMember)

    async def test_unmute_failure(self, dp, bot, session):
        session.errors[RestrictChatMember] = TelegramBadRequest(method=None, message="Bad Request")
        await cmd(dp, bot, "/unmute", reply=reply_to())
        assert "bo'lmadi" in replies(session)[0]


async def test_stats(dp, bot, session):
    session.member_count = 1234
    await cmd(dp, bot, "/stats")
    assert "1234" in replies(session)[0]


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

    async def test_members_who_left_are_dropped_from_tracking(self, dp, bot, session):
        await dbm.add_member(G, 5)
        session.statuses[(G, 5)] = "left"
        await cmd(dp, bot, "/kick_deleted")
        assert 5 not in await dbm.get_members(G) and not session.of(BanChatMember)

    async def test_unknown_member_is_dropped(self, dp, bot, session):
        await dbm.add_member(G, 5)
        session.errors[GetChatMember] = lambda m: TelegramBadRequest(method=m, message="Bad Request: user not found") \
            if m.user_id == 5 else None
        await cmd(dp, bot, "/kick_deleted")
        assert 5 not in await dbm.get_members(G)

    async def test_forbidden_counts_as_failure_and_keeps_tracking(self, dp, bot, session):
        await dbm.add_member(G, 5)
        session.errors[GetChatMember] = lambda m: TelegramForbiddenError(method=m, message="Forbidden") \
            if m.user_id == 5 else None
        await cmd(dp, bot, "/kick_deleted")
        assert 5 in await dbm.get_members(G) and "xato: 1" in edits_text(session)

    async def test_ban_failure_is_counted_and_loop_continues(self, dp, bot, session):
        for uid in (1, 2):
            await dbm.add_member(G, uid)
            session.names[uid] = "Deleted Account"
        session.errors[BanChatMember] = lambda m: TelegramBadRequest(method=m, message="Bad Request: x") \
            if m.user_id == 1 else None
        await cmd(dp, bot, "/kick_deleted")
        assert "chiqarildi: 1" in edits_text(session) and "xato: 1" in edits_text(session)
        assert 1 in await dbm.get_members(G) and 2 not in await dbm.get_members(G)

    async def test_other_groups_are_untouched(self, dp, bot, session):
        await dbm.add_member(G - 1, 9)
        session.names[9] = "Deleted Account"
        await cmd(dp, bot, "/kick_deleted")
        assert not session.of(BanChatMember) and await dbm.get_members(G - 1) == [9]

    async def test_empty_group(self, dp, bot, session):
        await cmd(dp, bot, "/kick_deleted")
        # buyruq bergan adminning o'zi ham kuzatuvdagi a'zo (middleware yozib qo'ygan)
        assert "Tekshirildi: 1" in edits_text(session) and "chiqarildi: 0" in edits_text(session)

    async def test_user_with_real_name_deleted_lookalike_is_not_kicked(self, dp, bot, session):
        await dbm.add_member(G, 1)
        session.names[1] = "deleted account"  # boshqa yozilish: haqiqiy foydalanuvchi bo'lishi mumkin
        await cmd(dp, bot, "/kick_deleted")
        assert not session.of(BanChatMember)


def edits_text(session) -> str:
    return "\n".join(m.text for m in session.of(EditMessageText))


class TestFinish:
    async def _voting(self, dp, bot, user=1):
        app_id = await start_application(dp, bot, user_id=user)
        await admin_accept(dp, bot, app_id)
        app = await dbm.get_application(app_id)
        bot.session.clear()
        return app_id, app["vote_message_id"]

    def _vote_message(self, message_id):
        return tf.group_message_obj(555, "vote", message_id=message_id)

    async def test_requires_reply(self, dp, bot, session):
        app_id, _ = await self._voting(dp, bot)
        await cmd(dp, bot, "/finish")
        assert "javob bergan holda" in replies(session)[0]
        assert await status_of(app_id) == "voting"

    async def test_reply_to_non_vote_message(self, dp, bot, session):
        app_id, _ = await self._voting(dp, bot)
        await cmd(dp, bot, "/finish", reply=self._vote_message(1))
        assert "ovoz berish xabari emas" in replies(session)[0]
        assert await status_of(app_id) == "voting"

    async def test_finishes_only_that_application(self, dp, bot, session):
        a, msg_a = await self._voting(dp, bot, user=1)
        b, _ = await self._voting(dp, bot, user=2)
        await cast(dp, bot, 200, "yes", a)
        session.clear()
        await cmd(dp, bot, "/finish", reply=self._vote_message(msg_a))
        assert await status_of(a) == "accepted" and await status_of(b) == "voting"

    async def test_tie_sends_only_the_decision_report_to_admin_no_summary(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        await cast(dp, bot, 200, "yes", app_id)
        await cast(dp, bot, 201, "no", app_id)
        session.clear()
        await cmd(dp, bot, "/finish", reply=self._vote_message(msg))
        dm = session.sent_to(A)
        assert len(dm) == 1 and dm[0].reply_markup is not None  # faqat qaror tugmali hisobot
        assert not any("🏁" in t or "Ovoz berish yakunlandi" in t for t in session.texts_to(A))
        assert replies(session) == ["🏁 Ovoz berish yakunlandi."]
        assert await status_of(app_id) == "creator_review"

    async def test_accepted_finish_sends_nothing_to_admin_dm(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        await cast(dp, bot, 200, "yes", app_id)
        session.clear()
        await cmd(dp, bot, "/finish", reply=self._vote_message(msg))
        assert await status_of(app_id) == "accepted"
        assert session.texts_to(A) == []
        assert replies(session) == ["🏁 Ovoz berish yakunlandi."]

    async def test_no_votes_finish_sends_nothing_to_admin_dm(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        session.clear()
        await cmd(dp, bot, "/finish", reply=self._vote_message(msg))
        assert await status_of(app_id) == "expired" and session.texts_to(A) == []

    async def test_second_finish_says_already_finished(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        await cast(dp, bot, 200, "yes", app_id)
        await cmd(dp, bot, "/finish", reply=self._vote_message(msg))
        session.clear()
        await cmd(dp, bot, "/finish", reply=self._vote_message(msg))
        # xabar o'chirilgan bo'lsa ham baza yozuvi bor: "yakunlangan" deyiladi
        assert "allaqachon yakunlangan" in replies(session)[0]

    async def test_vote_message_from_other_group_does_not_match(self, dp, bot, session):
        app_id, msg = await self._voting(dp, bot)
        other = tf.group_message(A, "/finish", chat_id=G - 1,
                                 reply_to=tf.group_message_obj(555, "v", chat_id=G - 1, message_id=msg))
        await feed(dp, bot, other)
        assert await status_of(app_id) == "voting"


class TestCommandCleanup:
    async def test_handled_admin_command_is_queued_for_deletion(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(A, "/stats", message_id=555))
        rows = await dbm.get_pending_deletes()
        assert any(r["chat_id"] == G and r["message_id"] == 555 for r in rows)

    async def test_non_admin_command_is_ignored_but_deleted_from_chat(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(555, "/stats", message_id=556))
        assert session.requests == []  # bot javob bermaydi
        assert any(r["chat_id"] == G and r["message_id"] == 556 for r in await dbm.get_pending_deletes())

    @pytest.mark.parametrize("command", ["/ban", "/unban", "/mute", "/unmute", "/stats", "/finish", "/kick_deleted"])
    async def test_every_non_admin_command_is_queued_for_deletion(self, dp, bot, session, command):
        await feed(dp, bot, tf.group_message(555, command, message_id=600))
        assert any(r["message_id"] == 600 for r in await dbm.get_pending_deletes())

    async def test_non_admin_command_for_another_bot_is_not_touched(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(555, "/stats@some_other_bot", message_id=601))
        assert all(r["message_id"] != 601 for r in await dbm.get_pending_deletes())

    async def test_non_admin_plain_text_is_not_touched(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(555, "salom", message_id=602))
        assert all(r["message_id"] != 602 for r in await dbm.get_pending_deletes())

    async def test_unrelated_command_of_a_non_admin_is_not_touched(self, dp, bot, session):
        # boshqa botlarning buyruqlari (/weather va h.k.) bizniki emas
        await feed(dp, bot, tf.group_message(555, "/weather", message_id=603))
        assert all(r["message_id"] != 603 for r in await dbm.get_pending_deletes())

    async def test_bot_replies_in_group_are_queued_too(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(A, "/stats", message_id=557))
        # SendMessage javobi (soxta xabar id'si) ham navbatda; sessiya middleware'i main.py da ulanadi
        assert session.of(SendMessage)


class TestMemberTracking:
    async def test_group_messages_track_senders(self, dp, bot, session):
        await feed(dp, bot, tf.group_message(5, "salom"))
        assert await dbm.get_members(G) == [5]

    async def test_bots_are_not_tracked(self, dp, bot, session):
        raw = tf.group_message(5, "salom").model_dump(mode="json", by_alias=True, exclude_none=True)
        raw["message"]["from"]["is_bot"] = True
        await dp.feed_raw_update(bot, raw)
        assert await dbm.get_members(G) == []

    async def test_private_messages_are_not_tracked(self, dp, bot, session):
        await feed(dp, bot, tf.private_message(5, "salom"))
        assert await dbm.get_known_group_ids() == []

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

    def _member_update(self, user_id, status, is_bot=False, **extra):
        user = {"id": user_id, "is_bot": is_bot, "first_name": "U"}
        return Update.model_validate({
            "update_id": 1,
            "chat_member": {
                "chat": {"id": G, "type": "supergroup", "title": "G"},
                "from": {"id": 1, "is_bot": False, "first_name": "A"},
                "date": 1700000000,
                "old_chat_member": {"status": "left", "user": user},
                "new_chat_member": {"status": status, "user": user, **extra},
            },
        })

    async def test_chat_member_join_tracks(self, dp, bot, session):
        await feed(dp, bot, self._member_update(11, "member"))
        assert await dbm.get_members(G) == [11]

    async def test_chat_member_leave_untracks(self, dp, bot, session):
        await dbm.add_member(G, 11)
        await feed(dp, bot, self._member_update(11, "left"))
        assert await dbm.get_members(G) == []

    async def test_chat_member_kicked_untracks(self, dp, bot, session):
        await dbm.add_member(G, 11)
        await feed(dp, bot, self._member_update(11, "kicked", until_date=0))
        assert await dbm.get_members(G) == []

    async def test_restricted_member_who_stays_is_tracked_but_one_who_left_is_not(self, dp, bot, session):
        perms = {k: False for k in (
            "can_send_messages", "can_send_audios", "can_send_documents", "can_send_photos", "can_send_videos",
            "can_send_video_notes", "can_send_voice_notes", "can_send_polls", "can_send_other_messages",
            "can_add_web_page_previews", "can_react_to_messages", "can_edit_tag", "can_change_info",
            "can_invite_users", "can_pin_messages", "can_manage_topics")}
        await feed(dp, bot, self._member_update(12, "restricted", is_member=True, until_date=0, **perms))
        assert await dbm.get_members(G) == [12]
        await feed(dp, bot, self._member_update(12, "restricted", is_member=False, until_date=0, **perms))
        assert await dbm.get_members(G) == []

    async def test_bot_accounts_are_ignored(self, dp, bot, session):
        await feed(dp, bot, self._member_update(13, "member", is_bot=True))
        assert await dbm.get_members(G) == []


class TestBotAddedToGroup:
    def _my_chat_member(self, status, **extra):
        me = {"id": tf.BOT_ID, "is_bot": True, "first_name": "Bot", "username": tf.BOT_USERNAME}
        return Update.model_validate({
            "update_id": 2,
            "my_chat_member": {
                "chat": {"id": G, "type": "supergroup", "title": "G"},
                "from": {"id": A, "is_bot": False, "first_name": "A"},
                "date": 1700000000,
                "old_chat_member": {"status": "left", "user": me},
                "new_chat_member": {"status": status, "user": me, **extra},
            },
        })

    async def test_adding_bot_sets_admin_menu_for_every_admin(self, dp, bot, session):
        await feed(dp, bot, self._my_chat_member("member"))
        scopes = session.of(SetMyCommands)
        assert sorted(s.scope.user_id for s in scopes) == [tf.ADMIN_ID, tf.ADMIN2_ID]
        assert all(s.scope.chat_id == G for s in scopes)
        assert {c.command for c in scopes[0].commands} >= {"ban", "finish", "kick_deleted"}

    async def test_removing_bot_sets_nothing(self, dp, bot, session):
        await feed(dp, bot, self._my_chat_member("left"))
        assert not session.of(SetMyCommands)

    async def test_menu_failure_for_one_admin_does_not_stop_the_other(self, dp, bot, session):
        session.errors[SetMyCommands] = lambda m: TelegramBadRequest(method=m, message="Bad Request: user not found") \
            if m.scope.user_id == tf.ADMIN_ID else None
        await feed(dp, bot, self._my_chat_member("member"))
        assert len(session.of(SetMyCommands)) == 2
        assert_no_errors(session)
