"""The Alembic chain, in one place, for the two layers that need a schema.

`tests/backend/conftest.py` and `tests/ui/conftest.py` each built their own
`Config` and called `command.upgrade(config, "head")` **per test**. That is
where the commit gate's time went: one chain costs ~220 ms, and 1050 of the
2460 tests in `just test` paid it, which is ~230 s — more than a third of the
serial suite, and nothing about it varied between tests.

So the chain runs **once per session** into a template database, and each test
copies that file (~0.1 ms). sw-design.md §11.2's guarantee is unchanged in
substance: every migration still executes on every backend run, against a real
temp-file SQLite database, and `alembic check` still has something real to
check. It executes once for the run rather than once per test.

`tests/backend/persistence/test_migrations.py` is the exception and keeps a
genuine per-test upgrade (`freshly_migrated`): a test named
"upgrade head creates every table" must not be asserting against a file copy.

**Synchronous on purpose.** `migrations/env.py` calls `asyncio.run`, which
cannot re-enter a loop an async fixture is already running on — the same
reason `tests/ui/conftest.py`'s `migrated_db` has always been sync.
"""

import shutil
from argparse import Namespace
from pathlib import Path

from alembic import command
from alembic.config import Config

from ra2.infra.config import Settings

__all__ = ["REPO_ROOT", "build_template", "copy_template", "upgrade_to_head"]

#: `tests/fixtures/migrations.py` -> `tests/fixtures` -> `tests` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


def upgrade_to_head(settings: Settings) -> None:
    """Run the real migration chain against `settings`'s database.

    Pointed at the database through the `-x url=` override `env.py` reads
    (the frozen `migrations/env.py`), so no environment variable is required.
    """
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "ra2" / "persistence" / "migrations"))
    # Mirrors what `-x url=...` would set from the CLI: `context.get_x_argument`
    # reads `config.cmd_opts.x`, a list of "key=value" strings.
    config.cmd_opts = Namespace(x=[f"url={settings.database_url}"])
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(config, "head")


def build_template(root: Path) -> Path:
    """Migrate a database at head under `root` and return its path.

    `db_path` is passed explicitly rather than left to default off `data_dir`,
    so an ambient `RA2_DB_PATH` cannot point the session's template at a
    developer's own database.
    """
    data_dir = root / "data"
    settings = Settings(data_dir=data_dir, db_path=data_dir / "ra2.sqlite", _env_file=None)
    upgrade_to_head(settings)
    return settings.database_path


def copy_template(template: Path, settings: Settings) -> Settings:
    """Put a database at head where `settings` expects one, and return it.

    A plain file copy. WAL and `-shm` belong to a *connection*, not to the
    schema, and the template's last connection is long closed — SQLite
    checkpoints and removes them on that close, so in practice there is one
    file to copy and `create_engine` re-establishes the rest per test through
    its connect-time PRAGMAs. The sidecars are copied **if they are there**
    anyway: a `-wal` left behind holds committed frames, and copying the main
    file alone would hand the test a schema with the tail missing — a failure
    that would read as "the migration did not run" rather than as what it was.
    """
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template, settings.database_path)
    for suffix in ("-wal", "-shm"):
        sidecar = template.with_name(template.name + suffix)
        if sidecar.exists():
            shutil.copy(
                sidecar, settings.database_path.with_name(settings.database_path.name + suffix)
            )
    return settings
