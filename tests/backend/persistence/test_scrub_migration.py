"""Revision `5b93f1f9617a` (sw-design.md §19.4, `SD62`) alters `corpus` in
place, in both directions.

Migrations run with `foreign_keys=ON`, so a batch rebuild of `corpus` (copy,
drop, rename) would cascade-delete every `record` and every row below it. That
is the hazard this file exists for: rows written before the upgrade must still
be there after it, and after the downgrade.
"""

import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.config import Config

from ra2.infra.config import Settings

pytestmark = pytest.mark.backend

BEFORE = "3ce2190bd859"
SCRUB = "5b93f1f9617a"
SCRUB_COLUMNS = {"scrub_ruleset_id", "scrub_fingerprint", "scrub_mandatory_json"}


def _insert_placeholder_row(conn: sqlite3.Connection, table: str, **fixed: object) -> None:
    """One row with a placeholder for every NOT NULL column without a default,
    read off the table, as `test_migration_backfills_parallel_calls_as_one`
    does, so this test does not need editing when the table grows. Stdlib
    `sqlite3` leaves foreign keys off, so the rows need no other parents."""
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    numeric = {"FLOAT", "REAL", "BOOLEAN"}
    values: dict[str, object] = {
        name: (0 if "INT" in kind.upper() or kind.upper() in numeric else "x")
        for _, name, kind, notnull, default, _ in columns
        if notnull and default is None
    }
    values.update(fixed)
    names = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(values.values()))


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _corpus_columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(corpus)")}


def test_records_survive_the_upgrade_and_the_downgrade(
    alembic_config: Config, backend_settings: Settings
) -> None:
    backend_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config, BEFORE)
    with closing(sqlite3.connect(backend_settings.database_path)) as conn, conn:
        _insert_placeholder_row(conn, "corpus", id="corpus-before-scrubbing", version=1)
        _insert_placeholder_row(
            conn, "record", id="record-before-scrubbing", corpus_id="corpus-before-scrubbing"
        )
        before = _tables(conn)

    command.upgrade(alembic_config, SCRUB)
    with closing(sqlite3.connect(backend_settings.database_path)) as conn:
        assert _tables(conn) == before | {"scrub_list", "scrub_ruleset"}
        assert _corpus_columns(conn) >= SCRUB_COLUMNS
        assert conn.execute("SELECT id FROM record").fetchall() == [("record-before-scrubbing",)]

    command.downgrade(alembic_config, BEFORE)
    with closing(sqlite3.connect(backend_settings.database_path)) as conn:
        assert _tables(conn) == before
        assert not SCRUB_COLUMNS & _corpus_columns(conn)
        assert conn.execute("SELECT id FROM record").fetchall() == [("record-before-scrubbing",)]

    command.upgrade(alembic_config, "head")


def test_a_corpus_from_before_reads_as_not_scrubbed(
    alembic_config: Config, backend_settings: Settings
) -> None:
    """No backfill: a corpus frozen before scrubbing existed was frozen
    verbatim, and three `NULL`s say exactly that (the `NOT SCRUBBED` chip)."""
    backend_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config, BEFORE)
    with closing(sqlite3.connect(backend_settings.database_path)) as conn, conn:
        _insert_placeholder_row(conn, "corpus", id="corpus-before-scrubbing", version=1)

    command.upgrade(alembic_config, "head")
    with closing(sqlite3.connect(backend_settings.database_path)) as conn:
        rows = conn.execute(
            "SELECT scrub_ruleset_id, scrub_fingerprint, scrub_mandatory_json FROM corpus"
        ).fetchall()
    assert rows == [(None, None, None)]
