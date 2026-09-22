"""Layer 2 shared fixtures: a real temporary-file SQLite database, migrated.

Owned by A3 in Wave 1 (plan-m0-m5.md §4's per-layer-conftest convention: the
first agent to land backend-layer tests owns `tests/backend/conftest.py`
until a later wave's owner needs to extend it).

**Never `:memory:`.** WAL and cross-connection behaviour only show up against
a real file, and that is exactly what the FK-enforcement and `busy_timeout`
tests in `tests/backend/persistence/` need to exercise (sw-design.md §11.2).

The schema always comes from `alembic upgrade head` — never
`ra2.persistence.models.Base.metadata.create_all()` (§12.10). It comes from it
**once per session**, into a template database each test copies; see
`tests/fixtures/migrations.py` for why, and for the one test that still runs
the chain itself.
"""

from argparse import Namespace
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fixtures.migrations import build_template, copy_template, upgrade_to_head

from ra2.infra.config import Settings
from ra2.persistence.session import create_engine, create_session_factory

__all__ = [
    "REPO_ROOT",
    "alembic_config",
    "backend_settings",
    "db_session",
    "db_session_factory",
    "freshly_migrated",
    "migrated_engine",
    "migrated_template",
    "run_upgrade_head",
]

#: `tests/backend/conftest.py` -> `tests/backend` -> `tests` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def backend_settings(tmp_path: Path) -> Settings:
    """Settings pointed at a fresh temp directory. Never the developer's own
    `./var`, and never shared between tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=data_dir, _env_file=None)


@pytest.fixture
def alembic_config(backend_settings: Settings) -> Config:
    """An `alembic.ini`-backed `Config`, pointed at `backend_settings`'s DB
    through the `-x url=` override `env.py` reads (sw-design.md, frozen
    `migrations/env.py`) — no environment variable required."""
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "ra2" / "persistence" / "migrations"))
    # Mirrors what `-x url=...` would set from the CLI (`context.get_x_argument`
    # reads `config.cmd_opts.x`, a list of "key=value" strings).
    cfg.cmd_opts = Namespace(x=[f"url={backend_settings.database_url}"])
    return cfg


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The real migration chain, run once for the whole session.

    Every migration executes on every backend test run — that is what makes
    `alembic check` meaningful and what the round-trip / FK / busy_timeout
    tests are asserted against (sw-design.md §11.2). It executes **once per
    run** rather than once per test; under `-n`, once per worker.
    """
    return build_template(tmp_path_factory.mktemp("migrated-template"))


@pytest.fixture
def run_upgrade_head(migrated_template: Path, backend_settings: Settings) -> Settings:
    """A real temp-file SQLite database at head, private to this test.

    A copy of `migrated_template`, not a fresh chain: ~0.1 ms instead of
    ~220 ms, and byte-identical to what the chain produces. Still a real file
    (never `:memory:`), still never `metadata.create_all()`.
    """
    return copy_template(migrated_template, backend_settings)


@pytest.fixture
def freshly_migrated(backend_settings: Settings) -> Settings:
    """`alembic upgrade head` run for this test alone.

    For the tests **about** the migrations (`persistence/test_migrations.py`):
    a test named "upgrade head creates every table" must assert against a
    database the chain just built, not against a file copy of one. Everything
    else wants `run_upgrade_head`.
    """
    upgrade_to_head(backend_settings)
    return backend_settings


@pytest_asyncio.fixture
async def migrated_engine(run_upgrade_head: Settings) -> AsyncIterator[AsyncEngine]:
    """The same `create_engine()` the app uses, so the connect-time PRAGMAs
    (WAL, `foreign_keys=ON`, `busy_timeout`) apply here too."""
    engine = create_engine(run_upgrade_head.database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def db_session_factory(migrated_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(migrated_engine)


@pytest_asyncio.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """A single session per test. Repository tests commit or roll back
    explicitly; nothing here hides that behind an auto-commit."""
    async with db_session_factory() as session:
        yield session
