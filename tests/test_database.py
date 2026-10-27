"""database.py: har bir funksiya, chegara holatlar va poyga (race) holatlari."""
import asyncio

import aiosqlite
import pytest

import database as dbm
from tests.conftest import age_application, expire_voting

G = -100500


async def new_app(user_id=1, group_id=G, name="Aziz Karimov", **kw):
    return await dbm.create_application(user_id, group_id, name, "anketa\n", **kw)


class TestCreateApplication:
    async def test_returns_id_and_defaults(self, db):
        app_id = await new_app(tg_username="aziz", phone="+998901234567")
        app = await dbm.get_application(app_id)
        assert app["status"] == "pending"
        assert app["tg_username"] == "aziz" and app["phone"] == "+998901234567"
        assert app["vote_message_id"] is None and app["voting_ends_at"] is None

    async def test_second_open_application_same_group_is_rejected(self, db):
        assert await new_app() is not None
        assert await new_app() is None

    async def test_same_user_other_group_is_allowed(self, db):
        assert await new_app(group_id=G) is not None
        assert await new_app(group_id=G - 1) is not None

    async def test_other_user_same_group_is_allowed(self, db):
        assert await new_app(user_id=1) is not None
        assert await new_app(user_id=2) is not None

    @pytest.mark.parametrize("final", ["rejected", "accepted", "expired", "failed"])
    async def test_can_reapply_after_final_status(self, db, final):
        first = await new_app()
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET status = ? WHERE id = ?", (final, first))
        await d.commit()
        second = await new_app()
        assert second is not None and second != first

    @pytest.mark.parametrize("open_status", ["pending", "voting", "creator_review"])
    async def test_cannot_reapply_while_open(self, db, open_status):
        first = await new_app()
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET status = ? WHERE id = ?", (open_status, first))
        await d.commit()
        assert await new_app() is None

    async def test_concurrent_creates_produce_exactly_one(self, db):
        results = await asyncio.gather(*(new_app() for _ in range(10)))
        assert sum(r is not None for r in results) == 1

    async def test_name_with_quotes_and_unicode_is_stored_verbatim(self, db):
        name = "O'g'li \"Test\"; DROP TABLE applications;--"
        app_id = await new_app(name=name)
        assert (await dbm.get_application(app_id))["full_name"] == name
        assert await dbm.get_application(app_id) is not None

    async def test_null_full_name_is_rejected_by_schema(self, db):
        with pytest.raises(aiosqlite.IntegrityError):
            d = await dbm.get_db()
            await d.execute(
                "INSERT INTO applications (user_id, group_id, full_name, anketa) VALUES (1, 1, NULL, 'x')"
            )


class TestLookups:
    async def test_get_application_missing(self, db):
        assert await dbm.get_application(999) is None

    async def test_get_active_application(self, db):
        assert await dbm.get_active_application(1, G) is None
        app_id = await new_app()
        assert (await dbm.get_active_application(1, G))["id"] == app_id
        assert await dbm.get_active_application(1, G - 1) is None
        assert await dbm.get_active_application(2, G) is None

    async def test_get_active_ignores_finished(self, db):
        app_id = await new_app()
        await dbm.change_status(app_id, "pending", "rejected")
        assert await dbm.get_active_application(1, G) is None

    async def test_by_vote_message_is_scoped_to_group(self, db):
        app_id = await new_app()
        await dbm.set_vote_message(app_id, 55)
        assert (await dbm.get_application_by_vote_message(G, 55))["id"] == app_id
        assert await dbm.get_application_by_vote_message(G - 1, 55) is None
        assert await dbm.get_application_by_vote_message(G, 56) is None


class TestStatusTransitions:
    async def test_change_status_is_compare_and_swap(self, db):
        app_id = await new_app()
        assert await dbm.change_status(app_id, "pending", "rejected") is True
        assert await dbm.change_status(app_id, "pending", "rejected") is False
        assert (await dbm.get_application(app_id))["status"] == "rejected"

    async def test_change_status_wrong_old(self, db):
        app_id = await new_app()
        assert await dbm.change_status(app_id, "voting", "accepted") is False
        assert (await dbm.get_application(app_id))["status"] == "pending"

    async def test_change_status_unknown_app(self, db):
        assert await dbm.change_status(12345, "pending", "rejected") is False

    async def test_double_click_race_only_one_wins(self, db):
        app_id = await new_app()
        results = await asyncio.gather(*(dbm.change_status(app_id, "pending", "rejected") for _ in range(8)))
        assert results.count(True) == 1

    async def test_start_voting_sets_deadline(self, db):
        app_id = await new_app()
        assert await dbm.start_voting(app_id, 10) is True
        app = await dbm.get_application(app_id)
        assert app["status"] == "voting" and app["voting_ends_at"] is not None
        d = await dbm.get_db()
        row = await (await d.execute("SELECT datetime('now', '+9 minutes') < ?, datetime('now', '+11 minutes') > ?",
                                     (app["voting_ends_at"], app["voting_ends_at"]))).fetchone()
        assert tuple(row) == (1, 1)

    async def test_start_voting_only_from_pending(self, db):
        app_id = await new_app()
        await dbm.start_voting(app_id, 10)
        assert await dbm.start_voting(app_id, 10) is False

    async def test_start_voting_race(self, db):
        app_id = await new_app()
        results = await asyncio.gather(*(dbm.start_voting(app_id, 10) for _ in range(6)))
        assert results.count(True) == 1

    async def test_start_voting_huge_minutes_does_not_produce_null_deadline(self, db):
        # config VOTING_MINUTES ni cheklaydi, lekin funksiyaning o'zi ham NULL deadline qoldirmasligi kerak
        app_id = await new_app()
        await dbm.start_voting(app_id, 7 * 24 * 60)
        assert (await dbm.get_application(app_id))["voting_ends_at"] is not None


class TestDueVotings:
    async def test_not_due_until_deadline(self, db):
        app_id = await new_app()
        await dbm.start_voting(app_id, 10)
        assert await dbm.get_due_votings() == []
        await expire_voting(app_id)
        assert [a["id"] for a in await dbm.get_due_votings()] == [app_id]

    async def test_only_voting_status_is_due(self, db):
        app_id = await new_app()
        await expire_voting(app_id)  # pending, deadline yo'q
        assert await dbm.get_due_votings() == []

    async def test_end_voting_now_all_in_group(self, db):
        ids = []
        for uid in (1, 2, 3):
            ids.append(await new_app(user_id=uid))
            await dbm.start_voting(ids[-1], 10)
        other = await new_app(user_id=4, group_id=G - 1)
        await dbm.start_voting(other, 10)
        assert sorted(await dbm.end_voting_now(G)) == sorted(ids)
        assert sorted(a["id"] for a in await dbm.get_due_votings()) == sorted(ids)

    async def test_end_voting_now_single_app(self, db):
        a, b = await new_app(user_id=1), await new_app(user_id=2)
        await dbm.start_voting(a, 10)
        await dbm.start_voting(b, 10)
        assert await dbm.end_voting_now(G, b) == [b]
        assert [x["id"] for x in await dbm.get_due_votings()] == [b]

    async def test_end_voting_now_wrong_group_or_status(self, db):
        a = await new_app()
        assert await dbm.end_voting_now(G, a) == []  # pending
        await dbm.start_voting(a, 10)
        assert await dbm.end_voting_now(G - 1, a) == []  # boshqa guruh
        assert await dbm.get_due_votings() == []


class TestExpiredApplications:
    async def test_old_pending_is_expired(self, db):
        a = await new_app()
        await age_application(a, 4)
        assert [x["id"] for x in await dbm.get_expired_applications(3)] == [a]

    async def test_recent_pending_is_not(self, db):
        a = await new_app()
        await age_application(a, 2)
        assert await dbm.get_expired_applications(3) == []

    async def test_voting_never_expires_by_age(self, db):
        a = await new_app()
        await dbm.start_voting(a, 10)
        await age_application(a, 30)
        assert await dbm.get_expired_applications(3) == []

    async def test_creator_review_expires_by_voting_end_not_creation(self, db):
        a = await new_app()
        await dbm.start_voting(a, 10)
        await dbm.change_status(a, "voting", "creator_review")
        await age_application(a, 30)  # yaratilgan sana ahamiyatsiz
        assert await dbm.get_expired_applications(3) == []
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET voting_ends_at = datetime('now', '-4 days') WHERE id = ?", (a,))
        await d.commit()
        assert [x["id"] for x in await dbm.get_expired_applications(3)] == [a]

    async def test_boundary_exactly_days_is_not_yet_expired(self, db):
        a = await new_app()
        d = await dbm.get_db()
        await d.execute("UPDATE applications SET created_at = datetime('now', '-3 days', '+1 minute') WHERE id = ?", (a,))
        await d.commit()
        assert await dbm.get_expired_applications(3) == []


async def voting_app(**kw):
    a = await new_app(**kw)
    await dbm.start_voting(a, 10)
    return a


class TestVotes:
    async def test_add_vote_once(self, db):
        a = await voting_app()
        assert await dbm.add_vote(a, 10, "yes") is True
        assert await dbm.add_vote(a, 10, "no") is False  # ovozni o'zgartirib bo'lmaydi
        assert await dbm.get_vote(a, 10) == "yes"

    async def test_invalid_vote_value_is_not_stored(self, db):
        # INSERT OR IGNORE CHECK buzilishini ham yutadi: False qaytadi, bazaga hech narsa tushmaydi
        a = await new_app()
        assert await dbm.add_vote(a, 10, "maybe") is False
        assert await dbm.get_vote(a, 10) is None
        assert await dbm.count_votes(a) == (0, 0)

    async def test_get_vote_none(self, db):
        a = await new_app()
        assert await dbm.get_vote(a, 10) is None

    async def test_count_votes_empty(self, db):
        a = await new_app()
        assert await dbm.count_votes(a) == (0, 0)

    async def test_count_votes_mixed(self, db):
        a = await voting_app()
        for uid, v in [(10, "yes"), (11, "yes"), (12, "no"), (13, "yes"), (14, "no")]:
            await dbm.add_vote(a, uid, v)
        assert await dbm.count_votes(a) == (3, 2)

    async def test_count_votes_isolated_per_application(self, db):
        a, b = await voting_app(user_id=1), await voting_app(user_id=2)
        await dbm.add_vote(a, 10, "yes")
        await dbm.add_vote(b, 10, "no")
        assert await dbm.count_votes(a) == (1, 0)
        assert await dbm.count_votes(b) == (0, 1)

    async def test_concurrent_same_voter_counts_once(self, db):
        a = await voting_app()
        results = await asyncio.gather(*(dbm.add_vote(a, 10, "yes") for _ in range(8)))
        assert results.count(True) == 1
        assert await dbm.count_votes(a) == (1, 0)

    async def test_no_votes_with_reasons_in_order(self, db):
        a = await voting_app()
        await dbm.add_vote(a, 10, "no")
        await dbm.add_vote(a, 11, "yes")
        await dbm.add_vote(a, 12, "no")
        await dbm.set_vote_reason(a, 12, "sabab")
        rows = await dbm.get_no_votes(a)
        assert {r["voter_id"] for r in rows} == {10, 12}
        assert {r["voter_id"]: r["reason"] for r in rows} == {10: None, 12: "sabab"}


class TestPendingReason:
    async def _voting_app_with_no(self, voter=10):
        a = await new_app()
        await dbm.start_voting(a, 10)
        await dbm.add_vote(a, voter, "no")
        return a

    async def test_found_for_fresh_no_vote(self, db):
        a = await self._voting_app_with_no()
        pending = await dbm.get_pending_reason(10)
        assert pending == {"app_id": a, "applicant_name": "Aziz Karimov"}

    async def test_yes_vote_never_asks(self, db):
        a = await new_app()
        await dbm.start_voting(a, 10)
        await dbm.add_vote(a, 10, "yes")
        assert await dbm.get_pending_reason(10) is None

    async def test_none_after_reason_saved(self, db):
        a = await self._voting_app_with_no()
        await dbm.set_vote_reason(a, 10, "sabab")
        assert await dbm.get_pending_reason(10) is None

    async def test_none_after_voting_window_closed(self, db):
        a = await self._voting_app_with_no()
        await expire_voting(a)
        assert await dbm.get_pending_reason(10) is None

    async def test_none_after_status_changed(self, db):
        a = await self._voting_app_with_no()
        await dbm.change_status(a, "voting", "rejected")
        assert await dbm.get_pending_reason(10) is None

    async def test_none_after_24_hours(self, db):
        a = await self._voting_app_with_no()
        d = await dbm.get_db()
        await d.execute("UPDATE votes SET created_at = datetime('now', '-25 hours') WHERE application_id = ?", (a,))
        await d.commit()
        assert await dbm.get_pending_reason(10) is None

    async def test_latest_no_vote_is_chosen(self, db):
        old = await self._voting_app_with_no()
        d = await dbm.get_db()
        await d.execute("UPDATE votes SET created_at = datetime('now', '-2 hours') WHERE application_id = ?", (old,))
        await d.commit()
        a2 = await new_app(user_id=2)
        await dbm.start_voting(a2, 10)
        await dbm.add_vote(a2, 10, "no")
        assert (await dbm.get_pending_reason(10))["app_id"] == a2

    async def test_other_voter_is_not_matched(self, db):
        await self._voting_app_with_no(voter=10)
        assert await dbm.get_pending_reason(11) is None


class TestProfiles:
    async def test_roundtrip_with_unicode(self, db):
        data = {"full_name": "Азиз Каримов", "age": 25, "phone": None}
        await dbm.save_profile(7, data)
        assert await dbm.get_profile(7) == data

    async def test_missing(self, db):
        assert await dbm.get_profile(7) is None

    async def test_upsert_overwrites(self, db):
        await dbm.save_profile(7, {"a": 1})
        await dbm.save_profile(7, {"a": 2})
        assert await dbm.get_profile(7) == {"a": 2}

    async def test_isolated_per_user(self, db):
        await dbm.save_profile(7, {"a": 1})
        await dbm.save_profile(8, {"a": 2})
        assert await dbm.get_profile(7) == {"a": 1}


class TestMembers:
    async def test_add_remove_get(self, db):
        await dbm.add_member(G, 1)
        await dbm.add_member(G, 1)  # takror xato bermaydi
        await dbm.add_member(G, 2)
        await dbm.add_member(G - 1, 3)
        assert sorted(await dbm.get_members(G)) == [1, 2]
        await dbm.remove_member(G, 1)
        assert await dbm.get_members(G) == [2]

    async def test_remove_unknown_is_noop(self, db):
        await dbm.remove_member(G, 99)

    async def test_known_groups_union_of_applications_and_members(self, db):
        await new_app(group_id=-1)
        await dbm.add_member(-2, 1)
        await dbm.add_member(-1, 1)
        assert sorted(await dbm.get_known_group_ids()) == [-2, -1]


class TestPendingDeletes:
    async def test_add_get_remove(self, db):
        await dbm.add_pending_delete(G, 1, 100)
        await dbm.add_pending_delete(G, 1, 200)  # INSERT OR REPLACE
        assert await dbm.get_pending_deletes() == [{"chat_id": G, "message_id": 1, "delete_at": 200}]
        await dbm.remove_pending_delete(G, 1)
        assert await dbm.get_pending_deletes() == []


class TestInitAndMigration:
    async def test_init_is_idempotent(self, db):
        await dbm.init_db()
        await dbm.init_db()

    async def test_old_schema_gets_new_columns_and_backfilled_deadline(self, tmp_path, monkeypatch):
        path = str(tmp_path / "old.db")
        old = await aiosqlite.connect(path)
        await old.executescript(
            """
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, group_id INTEGER NOT NULL,
                full_name TEXT NOT NULL, anketa TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                vote_message_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE votes (
                application_id INTEGER NOT NULL, voter_id INTEGER NOT NULL, vote TEXT NOT NULL, reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (application_id, voter_id)
            );
            INSERT INTO applications (user_id, group_id, full_name, anketa, status) VALUES (1, 1, 'A B', 'x', 'voting');
            INSERT INTO applications (user_id, group_id, full_name, anketa, status) VALUES (2, 1, 'C D', 'x', 'pending');
            """
        )
        await old.commit()
        await old.close()

        monkeypatch.setattr(dbm, "DB_PATH", path)
        monkeypatch.setattr(dbm, "_conn", None)
        try:
            await dbm.init_db()
            voting = await dbm.get_application(1)
            pending = await dbm.get_application(2)
            assert voting["voting_ends_at"] is not None  # osilib qolgan "voting" ariza muddat oladi
            assert pending["voting_ends_at"] is None
            for col in ("first_name", "last_name", "tg_username", "phone"):
                assert col in voting
            d = await dbm.get_db()
            cols = {r["name"] for r in await (await d.execute("PRAGMA table_info(votes)")).fetchall()}
            assert "weight" in cols
        finally:
            await dbm.close_db()

    async def test_wal_mode_enabled(self, db):
        d = await dbm.get_db()
        assert (await (await d.execute("PRAGMA journal_mode")).fetchone())[0] == "wal"

    async def test_get_db_returns_single_shared_connection(self, db):
        conns = await asyncio.gather(*(dbm.get_db() for _ in range(10)))
        assert len({id(c) for c in conns}) == 1

    async def test_close_db_then_reopen(self, db):
        a = await new_app()
        await dbm.close_db()
        assert dbm._conn is None
        assert (await dbm.get_application(a))["id"] == a  # qayta ochiladi, ma'lumot saqlangan

    async def test_db_file_is_owner_only(self, db):
        import os
        import stat

        assert stat.S_IMODE(os.stat(dbm.DB_PATH).st_mode) == 0o600
