"""A discard leaves no readable narrative behind (sw-design.md §4.4, §18.7).

`secure_delete=ON` is asserted as a pragma value in
`tests/backend/persistence/test_session_pragmas.py`. This module asserts the
property that pragma exists for, through the real service against the real
temp-file database: after `discard_run`, the verbatim text that was in
`mismatch.evidence_span` is **not in the file**.

Two things make the assertion worth trusting, both of them borrowed from the
proxy section in `tests/backend/infra/test_ollama_client.py`:

- a **positive control before the discard** — the same search over the same
  files finds the text while the run still exists, so a search that silently
  matched nothing could not pass;
- a **control with the pragma off** (`test_the_search_can_tell_the_difference`)
  showing that this is a real gate: with SQLite's own default, the bytes
  survive the delete, which is the defect
  (`risk-assesment.md` B3, §8.5's reproduction) this closes.

The text searched for is synthesised here and never read from anywhere
(Do-NOT #13); `tmp_path` is the only database these tests touch.
"""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.backend.services.lifecycle.conftest import ScoredWorld

from ra2.infra.config import Settings
from ra2.persistence.models import Mismatch
from ra2.services.lifecycle_service import LifecycleService

pytestmark = pytest.mark.backend

#: Shaped like the thing that is actually at stake — an evidence span is a
#: fragment of a police narrative — and unmistakably synthetic, so a match in
#: a file is this test's own doing and nothing else's.
MARKER = "SYNTHETIC-EVIDENCE-SPAN-7f3c · der Lenker bremste vor dem Streifen"

#: Enough rows that the text lands on ordinary table pages rather than in a
#: single overflow page that a later write might reuse by luck.
CONTROL_ROWS = 200


def _database_bytes(database_path: Path) -> bytes:
    """The database **and its WAL**. Freed pages live in whichever of the two
    the last write went to, so searching only the `.sqlite` file would report
    a clean database while the text sat in the sidecar beside it."""
    blob = database_path.read_bytes() if database_path.exists() else b""
    wal = database_path.with_name(database_path.name + "-wal")
    if wal.exists():
        blob += wal.read_bytes()
    return blob


def _occurrences(database_path: Path) -> int:
    return _database_bytes(database_path).count(MARKER.encode("utf-8"))


async def test_a_discarded_evidence_span_leaves_no_readable_bytes(
    scored: ScoredWorld,
    lifecycle_service: LifecycleService,
    db_session_factory: async_sessionmaker[AsyncSession],
    migrated_engine: AsyncEngine,
    backend_settings: Settings,
) -> None:
    """The whole of §18's bargain: *this cannot be undone* has to mean the
    text is gone, not that the row is unreachable through SQL."""
    async with db_session_factory() as session:
        row = (
            await session.scalars(
                select(Mismatch).where(Mismatch.run_id == scored.tagged_run_id).limit(1)
            )
        ).one()
        row.evidence_span = MARKER
        await session.commit()

    assert _occurrences(backend_settings.database_path) > 0, (
        "positive control: the search must find the span while the run exists, "
        "or the assertion below is vacuous"
    )

    await lifecycle_service.discard_run(scored.tagged_run_id, force=True)

    # Closing every pooled connection checkpoints the WAL into the database
    # and removes it. Deterministic where `PRAGMA wal_checkpoint(TRUNCATE)`
    # can come back busy because another pooled connection is still open.
    await migrated_engine.dispose()

    assert _occurrences(backend_settings.database_path) == 0


def test_the_search_can_tell_the_difference(tmp_path: Path) -> None:
    """The control. Same shape, same search, SQLite's own `secure_delete`
    default — and the text survives the `DELETE`.

    Without this, `test_a_discarded_evidence_span_leaves_no_readable_bytes`
    would keep passing if someone removed the pragma and the file simply never
    contained what we were looking for. It also records the defect itself: this
    is what every discard did before the pragma was set.
    """
    database_path = tmp_path / "control.sqlite"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 0, (
            "this build's default is no longer 0 — the control below proves nothing, "
            "and the pragma in session.py is now the only thing keeping it at 0"
        )
        connection.execute("CREATE TABLE mismatch (id INTEGER PRIMARY KEY, evidence_span TEXT)")
        connection.executemany(
            "INSERT INTO mismatch (evidence_span) VALUES (?)",
            [(f"{MARKER} {index}",) for index in range(CONTROL_ROWS)],
        )
        connection.commit()
        connection.execute("DELETE FROM mismatch")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    assert _occurrences(database_path) > 0
