import asyncio
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
            voting_ends_at  TIMESTAMP
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_open
            ON applications (user_id, group_id)
            WHERE status IN ('pending', 'voting', 'creator_review');

        CREATE TABLE IF NOT EXISTS members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS fsm (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    # eski bazalar uchun: CREATE TABLE IF NOT EXISTS mavjud jadvalga ustun qo'shmaydi
    await _add_column(db, "applications", "voting_ends_at", "TIMESTAMP")
    await _add_column(db, "votes", "weight", "INTEGER NOT NULL DEFAULT 1")
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
    user_id: int, group_id: int, full_name: str, anketa: str
) -> int | None:
    """Ariza id'si; shu guruhga faol ariza allaqachon bo'lsa None."""
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO applications (user_id, group_id, full_name, anketa) VALUES (?, ?, ?, ?)",
            (user_id, group_id, full_name, anketa),
        )
    except aiosqlite.IntegrityError:
        return None
    await db.commit()
    return cur.lastrowid  # type: ignore


async def get_application(app_id: int) -> dict | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_expired_applications(days: int) -> list[dict]:
    """Admin ko'rib chiqmagan (pending) yoki ovoz berish tugaganidan beri `days` kun creator javobini
    kutayotgan (creator_review) arizalar.

    Ovoz berish bosqichidagi (voting) arizalar bu yerga kirmaydi: ularni `voting_ends_at` yopadi.
    """
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE "
        "(status = 'pending' AND created_at < datetime('now', ?)) OR "
        "(status = 'creator_review' AND voting_ends_at < datetime('now', ?))",
        (f"-{days} days", f"-{days} days"),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_active_application(user_id: int, group_id: int) -> dict | None:
    """Shu guruh uchun hali ko'rib chiqilayotgan (pending/voting) ariza."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM applications WHERE user_id = ? AND group_id = ? "
        "AND status IN ('pending', 'voting', 'creator_review') ORDER BY id DESC LIMIT 1",
        (user_id, group_id),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def change_status(app_id: int, old: str, new: str) -> bool:
    db = await get_db()
    cur = await db.execute(
        "UPDATE applications SET status = ? WHERE id = ? AND status = ?",
        (new, app_id, old),
    )
    await db.commit()
    return cur.rowcount == 1


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


async def set_vote_message(app_id: int, message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE applications SET vote_message_id = ? WHERE id = ?",
        (message_id, app_id),
    )
    await db.commit()


async def add_vote(app_id: int, voter_id: int, vote: str, weight: int = 1) -> bool:
    db = await get_db()
    cur = await db.execute(
        "INSERT OR IGNORE INTO votes (application_id, voter_id, vote, weight) "
        "VALUES (?, ?, ?, ?)",
        (app_id, voter_id, vote, weight),
    )
    await db.commit()
    return cur.rowcount == 1


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
        SELECT v.application_id AS app_id, a.full_name AS applicant_name
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
    """Vaznli ovozlar yig'indisi: (ha, yo'q)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT SUM(CASE WHEN vote = 'yes' THEN weight END), "
        "SUM(CASE WHEN vote = 'no' THEN weight END) "
        "FROM votes WHERE application_id = ?",
        (app_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return 0, 0

    yes, no = row
    return yes or 0, no or 0
