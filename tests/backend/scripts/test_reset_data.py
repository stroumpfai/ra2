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
import sys
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


@pytest.fixture
def populated(tmp_path: Path) -> Settings:
    """A data directory with something in every target."""
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.database_path.write_bytes(b"not really sqlite")
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
