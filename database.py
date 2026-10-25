import aiosqlite

DB_PATH = "bot.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS applications (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                group_id        INTEGER NOT NULL,
                full_name       TEXT NOT NULL,
                anketa          TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                vote_message_id INTEGER,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS votes (
                application_id INTEGER NOT NULL REFERENCES applications(id),
                voter_id       INTEGER NOT NULL,
                vote           TEXT NOT NULL CHECK (vote IN ('yes', 'no')),
                reason         TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (application_id, voter_id)
            );

            CREATE TABLE IF NOT EXISTS fsm (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        await db.commit()


async def create_application(
    user_id: int, group_id: int, full_name: str, anketa: str
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO applications (user_id, group_id, full_name, anketa) VALUES (?, ?, ?, ?)",
            (user_id, group_id, full_name, anketa),
        )
        await db.commit()
        return cur.lastrowid  # type: ignore


async def get_application(app_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def change_status(app_id: int, old: str, new: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE applications SET status = ? WHERE id = ? AND status = ?",
            (new, app_id, old),
        )
        await db.commit()
        return cur.rowcount == 1


async def set_vote_message(app_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE applications SET vote_message_id = ? WHERE id = ?",
            (message_id, app_id),
        )
        await db.commit()


async def add_vote(app_id: int, voter_id: int, vote: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO votes (application_id, voter_id, vote) VALUES (?, ?, ?)",
            (app_id, voter_id, vote),
        )
        await db.commit()
        return cur.rowcount == 1


async def get_pending_reason(voter_id: int) -> dict | None:
    """Oxirgi 24 soat ichidagi, sababi hali yozilmagan 'yo'q' ovozi."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT v.application_id AS app_id, a.full_name AS applicant_name
            FROM votes v JOIN applications a ON a.id = v.application_id
            WHERE v.voter_id = ? AND v.vote = 'no' AND v.reason IS NULL
              AND v.created_at > datetime('now', '-1 day')
            ORDER BY v.created_at DESC LIMIT 1
            """,
            (voter_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_vote_reason(app_id: int, voter_id: int, reason: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE votes SET reason = ? WHERE application_id = ? AND voter_id = ?",
            (reason, app_id, voter_id),
        )
        await db.commit()


async def count_votes(app_id: int) -> tuple[int, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT SUM(vote = 'yes'), SUM(vote = 'no') FROM votes WHERE application_id = ?",
            (app_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return 0, 0

        yes, no = row
        return yes or 0, no or 0
