import json
from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import (
    BaseStorage,
    DefaultKeyBuilder,
    StateType,
    StorageKey,
)

from database import get_db


class SQLiteStorage(BaseStorage):
    """FSM holati va ma'lumotlarini SQLite'da saqlaydi, bot qayta ishga tushsa ham yo'qolmaydi."""

    def __init__(self) -> None:
        self.key_builder = DefaultKeyBuilder(with_destiny=True)

    async def _get(self, key: str) -> str | None:
        db = await get_db()
        cur = await db.execute("SELECT value FROM fsm WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None

    async def _set(self, key: str, value: str | None) -> None:
        db = await get_db()
        if value is None:
            await db.execute("DELETE FROM fsm WHERE key = ?", (key,))
        else:
            await db.execute(
                "INSERT INTO fsm (key, value, updated_at) VALUES (?, ?, CAST(strftime('%s', 'now') AS INTEGER)) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value),
            )
        await db.commit()

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self._set(self.key_builder.build(key, "state"), value)

    async def state_age(self, key: StorageKey) -> int | None:
        """Holat oxirgi marta yozilganiga necha soniya bo'ldi (yozuv yoki vaqt belgisi yo'q bo'lsa None)."""
        db = await get_db()
        cur = await db.execute(
            "SELECT CAST(strftime('%s', 'now') AS INTEGER) - updated_at FROM fsm WHERE key = ?",
            (self.key_builder.build(key, "state"),),
        )
        row = await cur.fetchone()
        return row[0] if row and row[0] is not None else None

    async def get_state(self, key: StorageKey) -> str | None:
        return await self._get(self.key_builder.build(key, "state"))

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        value = json.dumps(dict(data)) if data else None
        await self._set(self.key_builder.build(key, "data"), value)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        value = await self._get(self.key_builder.build(key, "data"))
        return json.loads(value) if value else {}

    async def close(self) -> None:
        pass
