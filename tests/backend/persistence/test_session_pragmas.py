"""Connect-time PRAGMA behaviour (sw-design.md §4.4), asserted against a real
temporary-file SQLite database — never `:memory:`. WAL mode and per-connection
`foreign_keys` enforcement only show up against a real file.

**Amendment resolved**: `contracts/amendments/feat-m2-persistence.md`
diagnosed this branch's real symptom (WAL/FK silently not applying against the
real `aiosqlite` driver) but attributed it to un-drained PRAGMA result rows.
The lead traced the actual root cause further at integration: `_apply_pragmas`
guarded on `isinstance(dbapi_connection, sqlite3.Connection)`, but the real
async engine hands it an `AsyncAdapt_aiosqlite_connection` — not a subclass —
so the guard returned early on *every* real connection and none of the three
pragmas ever ran. `busy_timeout` only looked correct by coincidence (this
SQLite build's own default is already 5000ms). Fixed in `session.py` by
widening the isinstance check; no `fetchone()` was actually needed.
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ra2.persistence.session import BUSY_TIMEOUT_MS

pytestmark = pytest.mark.backend


async def test_journal_mode_is_wal(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as conn:
        mode = await conn.exec_driver_sql("PRAGMA journal_mode")
        (value,) = mode.one()
    assert value.lower() == "wal"


async def test_busy_timeout_is_set(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA busy_timeout")
        (value,) = result.one()
    assert value == BUSY_TIMEOUT_MS


async def test_foreign_keys_pragma_is_on(migrated_engine: AsyncEngine) -> None:
    async with migrated_engine.connect() as conn:
        result = await conn.exec_driver_sql("PRAGMA foreign_keys")
        (value,) = result.one()
    assert value == 1


async def test_foreign_keys_are_actually_enforced(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SQLite defaults FK enforcement off; the frozen `session.py` is meant to
    turn it on at connect time. Proven by trying to violate a real FK and
    catching the resulting error — not merely reading the PRAGMA back
    (sw-design.md §11.2, plan-m0-m5.md A3 exit criteria).

    `delivery_file.delivery_id` has no `delivery` row behind it here.
    """
    async with db_session_factory() as session:
        orphan_file_id = str(uuid.uuid4())
        orphan_delivery_id = str(uuid.uuid4())
        insert = sa.text(
            "INSERT INTO delivery_file "
            "(id, delivery_id, filename, relative_path, byte_size, sha256, "
            " file_kind, ok_count, recovered_count, rejected_count, selected) "
            "VALUES (:id, :delivery_id, 'a.txt', 'a.txt', 0, 'x', 'unknown', 0, 0, 0, 1)"
        )
        params = {"id": orphan_file_id, "delivery_id": orphan_delivery_id}
        with pytest.raises(IntegrityError):
            await session.execute(insert, params)
        await session.rollback()
