#!/usr/bin/env python
"""`just reset` — wipe the data directory and bring the schema back up.

The **developer's** half of "reset" (plan-reset-and-discard.md §1). The
analyst's half is discarding runs in the app, and the two are deliberately
different tools: this one removes everything, without ceremony, and knows
nothing about guards, tags or exports.

Three properties, each of which has bitten someone:

1. **It resolves `Settings` exactly as the app does**, so it honours
   `RA2_DATA_DIR` and a `.env`. A reset that assumed `./var` would wipe the
   wrong directory for anyone who has moved theirs — or, worse, leave the real
   one full and the developer wondering why nothing changed.
2. **It prints what it will remove and refuses without the token.**
   `just reset` shows the plan; `just reset yes` carries it out. A destructive
   default is how the wrong database gets deleted at the end of a long day.
3. **The schema comes back through `alembic upgrade head`, in-process.** Never
   `metadata.create_all()` (Do-NOT #10) and never a subprocess (N3) — the
   migration chain is the only thing that may create a table here, exactly as
   in the app and in the backend tests.

`pathlib` for every path (N3). Nothing here opens a file, so there is no
`encoding=` to get wrong (N4); the one library call that touches the
filesystem in bulk is `shutil.rmtree`, which is stdlib and cross-platform, not
the shell-out N3 forbids.
"""

from __future__ import annotations

import shutil
import sys
from argparse import Namespace
from pathlib import Path

from alembic import command
from alembic.config import Config

from ra2.infra.config import Settings

#: `scripts/reset_data.py` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: The word that turns the plan into the act.
CONFIRM_TOKEN = "yes"


def _human(size: int) -> str:
    """`1048576` -> `"1.0 MB"`. Decimal units, matching the app's own
    `evaluation_view._gigabytes` rather than inventing a second convention."""
    value = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    raise AssertionError("unreachable")


def targets(settings: Settings) -> list[Path]:
    """Everything a reset removes, in the order it is printed.

    The SQLite sidecars are named explicitly rather than globbed: WAL mode
    means `-wal` and `-shm` hold committed data, and leaving them beside a
    deleted database is how a "wiped" directory comes back with rows in it.

    **There is no `exports/` target**, because the app writes no export to
    disk: all six are streamed to the browser and land in Downloads, where no
    RA2 verb reaches them. A reset that cleared an empty directory would read
    as though it had (risk-assesment.md B3 §8.6, `SD30`); `data-handling.md`
    §4 is where the analyst is told to go and delete them by hand.
    """
    database = settings.database_path
    return [
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
        settings.deliveries_dir,
        settings.codelists_dir,
    ]


def describe(path: Path) -> str:
    """One line: what it is, how much of it there is."""
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        return f"{path}  ({len(files)} file(s), {_human(sum(p.stat().st_size for p in files))})"
    if path.is_file():
        return f"{path}  ({_human(path.stat().st_size)})"
    return f"{path}  (absent)"


def remove(path: Path) -> bool:
    """Remove one target. Returns whether anything was there.

    A missing target is not an error: a reset run twice is a reset, and half a
    data directory is exactly the state this script exists to clear.
    """
    if path.is_dir():
        shutil.rmtree(path)
        return True
    if path.is_file():
        path.unlink()
        return True
    return False


def upgrade_head(settings: Settings) -> None:
    """`alembic upgrade head` against this data directory, in-process.

    The `-x url=` override is the one `migrations/env.py` reads, so nothing
    here depends on an environment variable being set the same way twice.
    """
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "ra2" / "persistence" / "migrations"))
    config.cmd_opts = Namespace(x=[f"url={settings.database_url}"])
    command.upgrade(config, "head")


def main(argv: list[str]) -> int:
    settings = Settings()
    planned = targets(settings)

    print(f"RA2_DATA_DIR: {settings.data_dir}")
    print("This would remove:")
    for path in planned:
        print(f"  {describe(path)}")

    if CONFIRM_TOKEN not in argv:
        print(f"\nNothing removed. Run `just reset {CONFIRM_TOKEN}` to carry this out.")
        return 0

    removed = sum(1 for path in planned if remove(path))
    print(f"\nRemoved {removed} of {len(planned)} target(s).")
    upgrade_head(settings)
    print(f"Schema at head: {settings.database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
