# FROZEN — see CONTRACTS.md
"""Async engine, the connect-time PRAGMAs, and the session factory (§4.4).

    SQLite, WAL, `foreign_keys=ON`, `busy_timeout=5000`, set as connect-time
    PRAGMAs in `session.py` — **nowhere else**.

They are connect-time because SQLAlchemy pools connections and `foreign_keys`
is per-connection: setting it once at startup silently leaves later connections
unenforced, which is exactly the bug the orphan-FK tests exist to catch.

`metadata.create_all()` appears nowhere, in the app or in tests (§12.10). The
schema comes from `alembic upgrade head`, always.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Connection as SQLite3Connection
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

__all__ = [
    "BUSY_TIMEOUT_MS",
    "SessionFactory",
    "create_engine",
    "create_session_factory",
    "session_scope",
]

#: sw-design.md §4.4. Long enough for a freeze transaction to finish while the
#: UI polls task progress on another connection.
BUSY_TIMEOUT_MS = 5000


class SessionFactory(Protocol):
    """What services are injected with. `async_sessionmaker` satisfies it."""

    def __call__(self) -> AsyncSession: ...


def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """The three connect-time PRAGMAs, on **every** pooled connection.

    - `journal_mode=WAL` — concurrent readers during a long freeze.
    - `foreign_keys=ON` — SQLite disables FK enforcement by default, so the
      orphan-FK checks would pass vacuously without this.
    - `busy_timeout` — wait rather than raise "database is locked".
    """
    if not isinstance(dbapi_connection, SQLite3Connection):  # pragma: no cover
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """One async engine, with the PRAGMAs bound to its connect event."""
    engine = create_async_engine(database_url, echo=echo, future=True)
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """`expire_on_commit=False` so a service can build a read model from an
    instance after committing, without a second round trip."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def ensure_database_dir(db_path: Path) -> None:
    """Create the parent directory of the SQLite file. `pathlib` only (N3)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One transaction, all-or-nothing.

    The freeze depends on this: a blocking validation failure must leave
    **zero** corpus rows, asserted by count rather than by absence of an
    exception (sw-design.md §11.2).
    """
    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()
