"""`scripts/reset_data.py` — the developer's wipe
(plan-reset-and-discard.md §5, §8).

A backend test rather than a unit one: it removes real files from a real temp
`RA2_DATA_DIR` and brings a real Alembic chain back up. The three properties
worth having a test for are the three that would hurt:

1. **It refuses without the token.** A destructive default is how the wrong
   database gets deleted at the end of a long day.
2. **It removes what it listed** — including the WAL sidecars, which hold
   committed rows and would otherwise repopulate a "wiped" database.
3. **It leaves the schema at head**, through the migration chain and never
   `metadata.create_all()` (Do-NOT #10).

`scripts/` is not a package, so the module is loaded by path — the same way a
script is actually run.
"""

import importlib.util
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, inspect

from ra2.infra.config import Settings

pytestmark = pytest.mark.backend

#: `tests/backend/scripts/` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def reset_data() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ra2_reset_data", REPO_ROOT / "scripts" / "reset_data.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sqlite(path: Path, *statements: str) -> None:
    """A real SQLite file holding exactly `statements`' tables and rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        for statement in statements:
            connection.execute(statement)
        connection.commit()


#: Only the columns `holdings` reads. Enough to be the thing it counts, and
#: nothing that could pass for a real row.
_CORPUS = "CREATE TABLE corpus (id TEXT, record_count INTEGER, is_synthetic BOOLEAN)"
_RUN = "CREATE TABLE run (id TEXT)"


@pytest.fixture
def populated(tmp_path: Path) -> Settings:
    """A data directory with something in every target. The database is a
    real SQLite file holding no corpus: an unreadable one now counts as
    possibly real (`SD46`), which is a different test."""
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    _sqlite(settings.database_path, "CREATE TABLE placeholder (x INTEGER)")
    settings.database_path.with_name(settings.database_path.name + "-wal").write_bytes(b"wal")
    for directory in (settings.deliveries_dir, settings.codelists_dir):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "something.txt").write_text("seed", encoding="utf-8")
    return settings


def test_without_the_token_nothing_is_removed(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)

    assert reset_data.main([]) == 0

    assert populated.database_path.is_file()
    assert (populated.deliveries_dir / "something.txt").is_file()


def test_the_token_removes_every_target_including_the_sidecars(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    wal = populated.database_path.with_name(populated.database_path.name + "-wal")

    assert reset_data.main(["yes"]) == 0

    assert not wal.exists()
    assert not populated.deliveries_dir.exists()
    assert not populated.codelists_dir.exists()


def test_the_plan_warns_that_a_running_app_must_be_stopped(
    reset_data: ModuleType,
    populated: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unlinking the database under a live process is a **split brain**, not a
    clean slate: it keeps the deleted inode on its pooled connections and
    opens the new file on every connection it makes afterwards, so it reads
    both (`plan-fix-results-visibility.md` §3.1).

    Printed with the **plan**, before the token is checked, because the dry
    run is the only place a person reliably reads this script's output — and
    because by the time the reset has happened the warning is too late.
    """
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)

    assert reset_data.main([]) == 0

    printed = capsys.readouterr().out
    assert "Stop the app first." in printed
    assert "Restart it after this." in printed


def test_a_reset_has_no_exports_target(reset_data: ModuleType, populated: Settings) -> None:
    """The absence is the contract (`SD30`, risk-assesment.md B3 §8.6).

    `Settings.exports_dir` existed, was documented as "where CSV exports are
    written", and was read by nothing but this script — so a reset cleared a
    directory the app never filled while the exports that matter sat in
    Downloads. Both halves are asserted here because either one coming back
    alone re-creates the same false reassurance.
    """
    assert not hasattr(populated, "exports_dir")
    assert all("exports" not in path.name for path in reset_data.targets(populated))


def test_the_schema_comes_back_at_head(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)

    reset_data.main(["yes"])

    engine = create_engine(f"sqlite:///{populated.database_path.as_posix()}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    # A representative table from every phase, plus Alembic's own bookkeeping
    # — which is what distinguishes a migrated database from a created one.
    assert {"corpus", "record", "feature", "run", "score", "mismatch"} <= tables
    assert "alembic_version" in tables


def test_a_second_reset_is_not_an_error(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Half a data directory is exactly the state this script exists to clear,
    so a missing target is not a failure."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)

    assert reset_data.main(["yes"]) == 0
    assert reset_data.main(["yes"]) == 0


def test_the_targets_are_all_under_the_data_dir(
    reset_data: ModuleType, populated: Settings
) -> None:
    """Nothing outside `RA2_DATA_DIR` is ever a target — the guarantee that
    makes running this on a developer's machine safe."""
    for path in reset_data.targets(populated):
        assert populated.data_dir.resolve() in path.resolve().parents


# --- what is lost, and the second token (risk E4, SD46) --------------------


def _with_corpora(settings: Settings, *rows: str, synthetic_column: bool = True) -> None:
    """Replace the fixture's database with one holding these corpus rows."""
    settings.database_path.unlink()
    corpus = _CORPUS if synthetic_column else _CORPUS.replace(", is_synthetic BOOLEAN", "")
    _sqlite(
        settings.database_path,
        corpus,
        _RUN,
        "INSERT INTO run VALUES ('r1'), ('r2'), ('r3')",
        *(f"INSERT INTO corpus VALUES {row}" for row in rows),
    )


def test_the_plan_says_what_is_lost_in_corpora_records_and_runs(
    reset_data: ModuleType,
    populated: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """E4: `ra2.sqlite 281.0 MB` is a hint. The operator decides on this."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 20, 0)", "('c2', 10, 1)")

    reset_data.main([])

    printed = capsys.readouterr().out
    assert "2 corpus(es), 30 records, 3 run(s); 1 of them NOT synthetic (20 records)" in printed


def test_yes_alone_does_not_destroy_a_real_corpus(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 20, 0)")

    assert reset_data.main(["yes"]) == 1

    assert reset_data.holdings(populated.database_path).real_corpora == 1
    assert (populated.deliveries_dir / "something.txt").is_file()


def test_the_second_token_destroys_it(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 20, 0)")

    assert reset_data.main(["yes", "destroy-real-data"]) == 0

    assert reset_data.holdings(populated.database_path).corpora == 0
    assert not populated.deliveries_dir.exists()


def test_the_second_token_alone_is_not_enough(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two different words, both required. Neither stands in for the other."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 20, 0)")

    assert reset_data.main(["destroy-real-data"]) == 0
    assert reset_data.holdings(populated.database_path).corpora == 1


def test_an_all_synthetic_database_needs_only_yes(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The developer's loop stays one word long."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 48, 1)", "('c2', 3000, 1)")

    assert reset_data.main(["yes"]) == 0
    assert reset_data.holdings(populated.database_path).corpora == 0


def test_a_database_from_before_sd45_counts_every_corpus_as_real(
    reset_data: ModuleType, populated: Settings
) -> None:
    """No `is_synthetic` column means nothing says any corpus is invented."""
    _with_corpora(populated, "('c1', 48)", "('c2', 12)", synthetic_column=False)

    held = reset_data.holdings(populated.database_path)
    assert (held.corpora, held.real_corpora, held.real_records) == (2, 2, 60)


def test_an_unreadable_database_counts_as_real(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard that fails open on a file it cannot read fails open on exactly
    the case nobody tested."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    populated.database_path.write_bytes(b"not really sqlite")

    assert reset_data.holdings(populated.database_path).may_hold_real_data
    assert reset_data.main(["yes"]) == 1
    assert populated.database_path.is_file()


def test_holdings_reads_the_schema_at_head(reset_data: ModuleType, populated: Settings) -> None:
    """The SQL runs against the real migrated schema, not only the fixture's."""
    populated.database_path.unlink()
    reset_data.upgrade_head(populated)

    held = reset_data.holdings(populated.database_path)
    assert held.readable
    assert held.corpora == 0


def test_holdings_writes_nothing(reset_data: ModuleType, populated: Settings) -> None:
    """Read-only: the dry run leaves the database byte-identical, sidecars too."""
    _with_corpora(populated, "('c1', 20, 0)")
    before = populated.database_path.read_bytes()

    reset_data.holdings(populated.database_path)

    assert populated.database_path.read_bytes() == before
    assert not populated.database_path.with_name(populated.database_path.name + "-shm").exists()


# --- `just reset-seed` ------------------------------------------------------


def test_reset_seed_without_yes_exits_non_zero_so_nothing_is_seeded(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recipe's second line runs the seed. It used to run it after a dry
    run too, straight on top of whatever database was there."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)

    assert reset_data.main(["--for-seed"]) == 1
    assert populated.database_path.is_file()


def test_reset_seed_refuses_real_data_whatever_the_tokens(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing a real corpus with a convincing invented one is never the
    right act. Destruction is `just reset yes destroy-real-data`, on its own."""
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 20, 0)")

    assert reset_data.main(["--for-seed", "yes", "destroy-real-data"]) == 1
    assert reset_data.holdings(populated.database_path).real_corpora == 1


def test_reset_seed_over_synthetic_data_carries_out(
    reset_data: ModuleType, populated: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reset_data, "Settings", lambda: populated)
    _with_corpora(populated, "('c1', 48, 1)")

    assert reset_data.main(["--for-seed", "yes"]) == 0
    assert reset_data.holdings(populated.database_path).corpora == 0
