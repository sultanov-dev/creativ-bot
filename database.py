import asyncio
import json
import os

import aiosqlite

from config import DATA_DIR, VOTING_MINUTES

DB_PATH = os.path.join(DATA_DIR, "bot.db")

_conn: aiosqlite.Connection | None = None
_conn_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    """Bitta umumiy ulanish: har so'rovda yangi ulanish ochilmaydi."""
    global _conn
    if _conn is None:
        async with _conn_lock:
            if _conn is None:
                conn = await aiosqlite.connect(DB_PATH, timeout=30)
                conn.row_factory = aiosqlite.Row
                try:
                    # anketa shaxsiy ma'lumot: faqat egasi o'qisin
                    os.chmod(DB_PATH, 0o600)
                except OSError:
                    pass
                # WAL: o'qish yozishni bloklamaydi; rejim faylda saqlanadi
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                _conn = conn
    return _conn


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def init_db() -> None:
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            group_id        INTEGER NOT NULL,
            full_name       TEXT NOT NULL,
            anketa          TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            vote_message_id INTEGER,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            voting_ends_at  TIMESTAMP,
            first_name      TEXT,
            last_name       TEXT,
            tg_username     TEXT,
            phone           TEXT,
            join_resolved   INTEGER NOT NULL DEFAULT 1,
            decided_at      TIMESTAMP,
            admins_notified INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS votes (
            application_id INTEGER NOT NULL REFERENCES applications(id),
            voter_id       INTEGER NOT NULL,
            vote           TEXT NOT NULL CHECK (vote IN ('yes', 'no')),
            reason         TEXT,
            weight         INTEGER NOT NULL DEFAULT 1,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (application_id, voter_id)
        );

        CREATE INDEX IF NOT EXISTS idx_votes_voter ON votes (voter_id, vote);
        CREATE INDEX IF NOT EXISTS idx_applications_user
            ON applications (user_id, group_id, status);
        -- bir vaqtda ikki xabar kelsa ham, bitta guruhga ikkita faol ariza bo'lmaydi
        DROP INDEX IF EXISTS idx_applications_active;
        -- eski nom (creator roli endi yo'q): holat va indeks yangilanadi
        UPDATE applications SET status = 'admin_decision' WHERE status = 'creator_review';
        DROP INDEX IF EXISTS idx_applications_open;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_open
            ON applications (user_id, group_id)
            WHERE status IN ('pending', 'voting', 'admin_decision');

        -- foydalanuvchining birinchi anketasi: qayta qo'shilganda savollar takrorlanmaydi
        CREATE TABLE IF NOT EXISTS profiles (
            user_id    INTEGER PRIMARY KEY,
            data       TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, user_id)
        );

        -- guruhdagi bot/buyruq xabarlarini keyinroq o'chirish navbati (bot qayta ishga tushsa ham saqlanadi)
        CREATE TABLE IF NOT EXISTS pending_deletes (
            chat_id    INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            delete_at  INTEGER NOT NULL,  -- unix vaqt, soniyada
            PRIMARY KEY (chat_id, message_id)
        );

        -- foydalanuvchi admin bilan gaplashmoqchi bo'lganda lichkadagi AI suhbat
        CREATE TABLE IF NOT EXISTS support_chats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            group_id    INTEGER NOT NULL,
            group_title TEXT,
            full_name   TEXT NOT NULL,
            tg_username TEXT,
            status      TEXT NOT NULL DEFAULT 'active',  -- awaiting_start | active | escalated | resolved
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_support_chats_user ON support_chats (user_id, status);

        CREATE TABLE IF NOT EXISTS support_messages (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role    TEXT NOT NULL,  -- user | assistant
            content TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fsm (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at INTEGER
        );
    """)
    # eski bazalar uchun: CREATE TABLE IF NOT EXISTS mavjud jadvalga ustun qo'shmaydi
    await _add_column(db, "applications", "voting_ends_at", "TIMESTAMP")
    await _add_column(db, "votes", "weight", "INTEGER NOT NULL DEFAULT 1")
    for column in ("first_name", "last_name", "tg_username", "phone"):
        await _add_column(db, "applications", column, "TEXT")
    # eski qatorlar uchun 1: ularning so'rovi allaqachon hal qilingan deb hisoblanadi
    await _add_column(db, "applications", "join_resolved", "INTEGER NOT NULL DEFAULT 1")
    # qaror vaqti: qayta ariza kutish muddati va eski ma'lumotlarni o'chirish shundan hisoblanadi
    await _add_column(db, "applications", "decided_at", "TIMESTAMP")
    # 0: anketa adminlarga hali yetkazilmagan (bot yuborish oralig'ida to'xtagan bo'lishi mumkin)
    await _add_column(db, "applications", "admins_notified", "INTEGER NOT NULL DEFAULT 1")
    # anketa holati oxirgi o'zgargan vaqt (unix soniya): tugallanmagan anketa muddati shundan hisoblanadi
    await _add_column(db, "fsm", "updated_at", "INTEGER")
    await db.execute(
        "UPDATE applications SET decided_at = created_at WHERE decided_at IS NULL "
        "AND status IN ('accepted', 'rejected', 'expired', 'failed', 'removed')"
    )
    await db.execute(
        "UPDATE applications SET voting_ends_at = datetime('now', ?) "
        "WHERE status = 'voting' AND voting_ends_at IS NULL",
        (f"+{VOTING_MINUTES} minutes",),
    )
    await db.commit()


async def _add_column(db: aiosqlite.Connection, table: str, column: str, ddl: str) -> None:
    cur = await db.execute(f"PRAGMA table_info({table})")
    if column not in {r["name"] for r in await cur.fetchall()}:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


async def create_application(
    user_id: int,
    group_id: int,
    full_name: str,
    anketa: str,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    tg_username: str | None = None,
    phone: str | None = None,
    admins_notified: bool = True,
) -> int | None:
    """Ariza id'si; shu guruhga faol ariza allaqachon bo'lsa None.

    full_name = ism va familiya (bitta savol); first_name/last_name faqat eski yozuvlar uchun.
    """
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO applications (user_id, group_id, full_name, anketa, "
            "first_name, last_name, tg_username, phone, admins_notified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, group_id, full_name, anketa, first_name, last_name, tg_username, phone, int(admins_notified)),
        )
    except aiosqlite.IntegrityError:
        return None
    await db.commit()
    return cur.lastrowid  # type: ignore


async def save_profile(user_id: int, data: dict) -> None:
    """Foydalanuvchining saqlangan anketasi: yo'q bo'lsa yaratiladi, bor bo'lsa yangilanadi (tahrirlanganda)."""
    db = await get_db()
    await db.execute(
        "INSERT INTO profiles (user_id, data) VALUES (?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
        (user_id, json.dumps(data, ensure_ascii=False)),
    )
    await db.commit()


async def get_profile(user_id: int) -> dict | None:
    db = await get_db()
    cur = await db.execute("SELECT data FROM profiles WHERE user_id = ?", (user_id,))
    row = await cur.fetchone()
    return json.loads(row["data"]) if row else None


async def get_application(app_id: int) -> dict | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_application_by_vote_message(group_id: int, message_id: int) -> dict | None:
    """Guruhdagi ovoz berish xabari (vote_message_id) bo'yicha ariza."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE group_id = ? AND vote_message_id = ?",
        (group_id, message_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_expired_applications(days: int) -> list[dict]:
    """Admin ko'rib chiqmagan (pending) yoki ovoz berish tugaganidan beri `days` kun adminlar javobini
    kutayotgan (admin_decision, ya'ni adminlar qaroriga) arizalar.

    Ovoz berish bosqichidagi (voting) arizalar bu yerga kirmaydi: ularni `voting_ends_at` yopadi.
    """
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE "
        "(status = 'pending' AND created_at < datetime('now', ?)) OR "
        "(status = 'admin_decision' AND voting_ends_at < datetime('now', ?))",
        (f"-{days} days", f"-{days} days"),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_active_application(user_id: int, group_id: int) -> dict | None:
    """Shu guruh uchun hali ko'rib chiqilayotgan (pending/voting) ariza."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE user_id = ? AND group_id = ? "
        "AND status IN ('pending', 'voting', 'admin_decision') ORDER BY id DESC LIMIT 1",
        (user_id, group_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def change_status(app_id: int, old: str, new: str) -> bool:
    """Atomik o'tish. Yakuniy holatga (accepted/rejected/expired) o'tganda guruh so'rovi hali hal qilinmagan
    deb belgilanadi (join_resolved = 0): bot shu oraliqda to'xtasa, startda qayta bajariladi."""
    db = await get_db()
    cur = await db.execute(
        "UPDATE applications SET status = ?, "
        "join_resolved = CASE WHEN ? IN ('accepted', 'rejected', 'expired') THEN 0 ELSE join_resolved END, "
        "decided_at = CASE WHEN ? IN ('accepted', 'rejected', 'expired', 'failed') "
        "THEN datetime('now') ELSE decided_at END "
        "WHERE id = ? AND status = ?",
        (new, new, new, app_id, old),
    )
    await db.commit()
    return cur.rowcount == 1


async def mark_join_resolved(app_id: int) -> None:
    db = await get_db()
    await db.execute("UPDATE applications SET join_resolved = 1 WHERE id = ?", (app_id,))
    await db.commit()


async def get_unresolved_join_requests() -> list[dict]:
    """Yakuniy holati yozilgan, lekin guruh so'rovi (approve/decline) bajarilmagan arizalar."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE join_resolved = 0 AND status IN ('accepted', 'rejected', 'expired')"
    )
    return [dict(r) for r in await cur.fetchall()]


async def mark_removed(user_id: int, group_id: int) -> int:
    """Admin guruhdan chiqargan/bloklagan foydalanuvchining qabul qilingan arizalari 'removed' bo'ladi:
    qayta qo'shilganda eski anketa bilan ovozga emas, yangi anketa va admin ko'rigiga boradi."""
    db = await get_db()
    cur = await db.execute(
        "UPDATE applications SET status = 'removed', decided_at = datetime('now') "
        "WHERE user_id = ? AND group_id = ? AND status = 'accepted'",
        (user_id, group_id),
    )
    await db.commit()
    return cur.rowcount


async def start_voting(app_id: int, minutes: int) -> bool:
    """pending -> voting va ovoz berish muddatini belgilaydi (bitta atomik UPDATE)."""
    db = await get_db()
    cur = await db.execute(
        "UPDATE applications SET status = 'voting', voting_ends_at = datetime('now', ?) "
        "WHERE id = ? AND status = 'pending'",
        (f"+{minutes} minutes", app_id),
    )
    await db.commit()
    return cur.rowcount == 1


async def get_due_votings() -> list[dict]:
    """Ovoz berish muddati tugagan, hali yakunlanmagan arizalar."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE status = 'voting' "
        "AND voting_ends_at <= datetime('now')"
    )
    return [dict(r) for r in await cur.fetchall()]


async def end_voting_now(group_id: int, app_id: int | None = None) -> list[int]:
    """Guruhdagi (yoki bitta) ovoz berilayotgan arizalarning muddatini hozirga tushiradi; id'larni qaytaradi."""
    db = await get_db()
    query = "SELECT id FROM applications WHERE status = 'voting' AND group_id = ?"
    params: list = [group_id]
    if app_id is not None:
        query += " AND id = ?"
        params.append(app_id)
    ids = [r[0] for r in await (await db.execute(query, params)).fetchall()]
    for i in ids:
        await db.execute(
            "UPDATE applications SET voting_ends_at = datetime('now') "
            "WHERE id = ? AND status = 'voting'",
            (i,),
        )
    await db.commit()
    return ids


async def get_known_group_ids() -> list[int]:
    """Bot ishlagan guruhlar (ariza yoki a'zo yozuvi bor)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT group_id FROM applications UNION SELECT chat_id FROM members"
    )
    return [r[0] for r in await cur.fetchall()]


async def set_vote_message(app_id: int, message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE applications SET vote_message_id = ? WHERE id = ?",
        (message_id, app_id),
    )
    await db.commit()


async def add_vote(app_id: int, voter_id: int, vote: str) -> bool:
    db = await get_db()
    # holat va muddat shu yerning o'zida tekshiriladi: yakunlash bilan poyga bo'lmasin (muddatdan keyingi ovoz yozilmaydi)
    cur = await db.execute(
        "INSERT OR IGNORE INTO votes (application_id, voter_id, vote) "
        "SELECT ?, ?, ? WHERE EXISTS (SELECT 1 FROM applications WHERE id = ? AND status = 'voting' "
        "AND (voting_ends_at IS NULL OR voting_ends_at > datetime('now')))",
        (app_id, voter_id, vote, app_id),
    )
    await db.commit()
    return cur.rowcount == 1


async def get_vote(app_id: int, voter_id: int) -> str | None:
    """Foydalanuvchining shu arizaga bergan ovozi ('yes'/'no') yoki None."""
    db = await get_db()
    cur = await db.execute(
        "SELECT vote FROM votes WHERE application_id = ? AND voter_id = ?",
        (app_id, voter_id),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def add_member(chat_id: int, user_id: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO members (chat_id, user_id) VALUES (?, ?)",
        (chat_id, user_id),
    )
    await db.commit()


async def remove_member(chat_id: int, user_id: int) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM members WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    )
    await db.commit()


async def get_members(chat_id: int) -> list[int]:
    db = await get_db()
    cur = await db.execute("SELECT user_id FROM members WHERE chat_id = ?", (chat_id,))
    return [r[0] for r in await cur.fetchall()]


async def get_pending_reason(voter_id: int) -> dict | None:
    """Oxirgi 24 soat ichidagi, sababi hali yozilmagan 'yo'q' ovozi (faqat ovoz berish davom etayotgan arizada)."""
    db = await get_db()
    cur = await db.execute(
        """
        SELECT v.application_id AS app_id, a.full_name AS applicant_name, a.group_id AS group_id
        FROM votes v JOIN applications a ON a.id = v.application_id
        WHERE v.voter_id = ? AND v.vote = 'no' AND v.reason IS NULL
          AND v.created_at > datetime('now', '-1 day')
          AND a.status = 'voting' AND a.voting_ends_at > datetime('now')
        ORDER BY v.created_at DESC LIMIT 1
        """,
        (voter_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def set_vote_reason(app_id: int, voter_id: int, reason: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE votes SET reason = ? WHERE application_id = ? AND voter_id = ?",
        (reason, app_id, voter_id),
    )
    await db.commit()


async def get_no_votes(app_id: int) -> list[dict]:
    """Arizaga 👎 bergan a'zolar (voter_id, reason), ovoz berish tartibida."""
    db = await get_db()
    cur = await db.execute(
        "SELECT voter_id, reason FROM votes "
        "WHERE application_id = ? AND vote = 'no' ORDER BY created_at",
        (app_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def count_votes(app_id: int) -> tuple[int, int]:
    """Ovozlar soni: (ha, yo'q). Har bir a'zo (admin ham) bitta ovoz beradi."""
    db = await get_db()
    cur = await db.execute(
        "SELECT SUM(vote = 'yes'), SUM(vote = 'no') "
        "FROM votes WHERE application_id = ?",
        (app_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return 0, 0

    yes, no = row
    return yes or 0, no or 0


async def add_pending_delete(chat_id: int, message_id: int, delete_at: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO pending_deletes (chat_id, message_id, delete_at) VALUES (?, ?, ?)",
        (chat_id, message_id, delete_at),
    )
    await db.commit()


async def remove_pending_delete(chat_id: int, message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM pending_deletes WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)
    )
    await db.commit()


async def get_pending_deletes() -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT chat_id, message_id, delete_at FROM pending_deletes")
    return [dict(r) for r in await cur.fetchall()]


async def last_application_status(user_id: int, group_id: int) -> str | None:
    """Foydalanuvchining shu guruhdagi oxirgi arizasi holati (yo'q bo'lsa None)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT status FROM applications WHERE user_id = ? AND group_id = ? ORDER BY id DESC LIMIT 1",
        (user_id, group_id),
    )
    row = await cur.fetchone()
    return row["status"] if row else None


async def rejoin_wait_seconds(user_id: int, group_id: int, cooldown: int) -> int:
    """Oxirgi ariza rad etilgan/muddati o'tgan/ko'rib chiqilmagan bo'lsa, yangi ariza uchun qolgan soniyalar (0 = erkin)."""
    if cooldown <= 0:
        return 0
    db = await get_db()
    cur = await db.execute(
        "SELECT status, CAST(strftime('%s', 'now') AS INTEGER) - CAST(strftime('%s', decided_at) AS INTEGER) AS age "
        "FROM applications WHERE user_id = ? AND group_id = ? ORDER BY id DESC LIMIT 1",
        (user_id, group_id),
    )
    row = await cur.fetchone()
    if row is None or row["age"] is None or row["status"] not in ("rejected", "expired", "failed"):
        return 0
    return max(0, cooldown - row["age"])


async def reset_orphan_votings() -> int:
    """Ovoz xabari guruhga yuborilishi bilan bot to'xtagan arizalar (voting, lekin xabar id'si yo'q): pending'ga qaytadi.

    Admin xabaridagi tugma saqlanib qolgani uchun qayta "Ovozga qo'yish" bosa oladi; guruhdagi eski yetim xabar
    tugma bosilganda eskirgan deb o'chiriladi.
    """
    db = await get_db()
    cur = await db.execute(
        "UPDATE applications SET status = 'pending', voting_ends_at = NULL "
        "WHERE status = 'voting' AND vote_message_id IS NULL"
    )
    await db.commit()
    return cur.rowcount


async def create_support_chat(
    user_id: int, group_id: int, group_title: str | None, full_name: str, tg_username: str | None, status: str
) -> int:
    db = await get_db()
    cur = await db.execute(
        "INSERT INTO support_chats (user_id, group_id, group_title, full_name, tg_username, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, group_id, group_title, full_name, tg_username, status),
    )
    await db.commit()
    return cur.lastrowid


async def get_support_chat(user_id: int, status: str, ttl_hours: int) -> dict | None:
    """Foydalanuvchining shu holatdagi oxirgi suhbati (oxirgi xabaridan ttl_hours dan oshmagan)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM support_chats WHERE user_id = ? AND status = ? AND updated_at > datetime('now', ?) "
        "ORDER BY id DESC LIMIT 1",
        (user_id, status, f"-{ttl_hours} hours"),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def set_support_status(chat_id: int, old: str, new: str) -> bool:
    """Atomik: faqat hozirgi holat old bo'lsa o'zgaradi (ikki marta uzatish/yopish bo'lmasin)."""
    db = await get_db()
    cur = await db.execute(
        "UPDATE support_chats SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = ?",
        (new, chat_id, old),
    )
    await db.commit()
    return cur.rowcount > 0


async def add_support_message(chat_id: int, role: str, content: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO support_messages (chat_id, role, content) VALUES (?, ?, ?)", (chat_id, role, content)
    )
    await db.execute("UPDATE support_chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
    await db.commit()


async def get_support_messages(chat_id: int) -> list[dict]:
    db = await get_db()
    cur = await db.execute("SELECT role, content FROM support_messages WHERE chat_id = ? ORDER BY id", (chat_id,))
    return [dict(r) for r in await cur.fetchall()]


async def purge_old_data(days: int) -> int:
    """Rad etilgan/muddati o'tgan/ko'rib chiqilmagan/chiqarilgan arizalarni `days` kundan keyin shaxsiy ma'lumotlari
    (anketa, telefon, ovozlar, sabablar) bilan o'chiradi; boshqa arizasi qolmagan foydalanuvchining saqlangan anketasi ham o'chadi."""
    if days <= 0:
        return 0
    db = await get_db()
    # lichkadagi AI suhbatlar ham shaxsiy ma'lumot: eskirgach o'chadi
    await db.execute(
        "DELETE FROM support_messages WHERE chat_id IN "
        "(SELECT id FROM support_chats WHERE updated_at < datetime('now', ?))",
        (f"-{days} days",),
    )
    await db.execute("DELETE FROM support_chats WHERE updated_at < datetime('now', ?)", (f"-{days} days",))
    await db.commit()
    cur = await db.execute(
        "SELECT id, user_id FROM applications "
        "WHERE status IN ('rejected', 'expired', 'failed', 'removed') AND decided_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    rows = await cur.fetchall()
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    users = {r["user_id"] for r in rows}
    marks = ",".join("?" * len(ids))
    await db.execute(f"DELETE FROM votes WHERE application_id IN ({marks})", ids)
    await db.execute(f"DELETE FROM applications WHERE id IN ({marks})", ids)
    for user_id in users:
        await db.execute(
            "DELETE FROM profiles WHERE user_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM applications WHERE user_id = ?)",
            (user_id, user_id),
        )
    await db.commit()
    return len(ids)


async def mark_admins_notified(app_id: int) -> None:
    db = await get_db()
    await db.execute("UPDATE applications SET admins_notified = 1 WHERE id = ?", (app_id,))
    await db.commit()


async def get_undelivered_applications() -> list[dict]:
    """To'liq anketa (ariza yaratilgan), lekin adminlarga yetkazilmagan pending arizalar."""
    db = await get_db()
    cur = await db.execute("SELECT * FROM applications WHERE status = 'pending' AND admins_notified = 0 ORDER BY id")
    return [dict(r) for r in await cur.fetchall()]
