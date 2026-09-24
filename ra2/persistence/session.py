# FROZEN — see CONTRACTS.md
"""Async engine, the connect-time PRAGMAs, and the session factory (§4.4).

    SQLite, WAL, `foreign_keys=ON`, `busy_timeout=5000`, `secure_delete=ON`,
    set as connect-time PRAGMAs in `session.py` — **nowhere else**.

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
from typing import Any, Final, Protocol

from sqlalchemy import event
from sqlalchemy.dialects.sqlite.aiosqlite import AsyncAdapt_aiosqlite_connection
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


#: The two DBAPI connection classes this app's engine ever hands to the
#: connect-time listener: the real `sqlite3.Connection` (used synchronously by
#: Alembic's offline mode and by direct `sqlite3` access, if any) and
#: SQLAlchemy's async adapter around `aiosqlite` (used by every real
#: `create_engine()` connection at runtime — see the bug note below).
_SQLITE_CONNECTION_TYPES: Final = (SQLite3Connection, AsyncAdapt_aiosqlite_connection)


def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """The four connect-time PRAGMAs, on **every** pooled connection.

    - `journal_mode=WAL` — concurrent readers during a long freeze.
    - `foreign_keys=ON` — SQLite disables FK enforcement by default, so the
      orphan-FK checks would pass vacuously without this.
    - `busy_timeout` — wait rather than raise "database is locked".
    - `secure_delete=ON` — SQLite frees a deleted row's page onto the freelist
      **with its bytes intact**, so a discarded run's `mismatch.evidence_span`
      (verbatim narrative, §18) stays readable in the file until some later
      write happens to reuse that page. This zeroes it at delete time. It is
      a connect-time pragma and not a `VACUUM` after each discard because a
      `VACUUM` is a second thing to remember, means nothing in WAL mode until
      a checkpoint, and cannot run inside the transaction a discard holds.
      The default is a **compile-time** property of whatever SQLite the
      interpreter bundles and reads back `0` on this one, so it is set rather
      than assumed (risk-assesment.md B3 §8.6).

    The isinstance check originally only matched `sqlite3.Connection`. Every
    real connection this app's async engine creates is actually an
    `AsyncAdapt_aiosqlite_connection`, which is not a subclass of
    `sqlite3.Connection` — so the check returned early on **every** real
    connection, and none of the pragmas (three, at the time) were ever applied.
    Caught at the M2 review gate (contracts/amendments/feat-m2-persistence.md)
    via a real-file-database test showing `foreign_keys` reading back `0`.
    """
    if not isinstance(dbapi_connection, _SQLITE_CONNECTION_TYPES):  # pragma: no cover
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA secure_delete=ON")
    finally:
        cursor.close()


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """One async engine, with the PRAGMAs bound to its connect event.

    `hide_parameters=True` is a **data-handling** flag, not a tuning one. Its
    default is `False`, which puts the bound parameters of a failing statement
    into `str(exc)` — and for an insert over `record` those parameters are
    `text_raw` and `unfall_uid`, both on `data-handling.md` §5.1's "may never
    appear" list by name. `run_service._error_text` stringifies every
    exception into `run.error`, which is persisted, shown by the runs table's
    log action and written to stderr, so a constraint violation published the
    narrative to the one artefact an operator is asked to paste into a bug
    report (risk-assesment.md A5 §9.2, `SD39`). It covers `echo=` too: the
    statement log goes through the same suppression.
    """
    engine = create_async_engine(database_url, echo=echo, future=True, hide_parameters=True)
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
