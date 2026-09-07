# FROZEN — see CONTRACTS.md
"""Alembic environment: async, and the URL comes from `Settings`.

Reading `RA2_DB_PATH` here (rather than hard-coding a URL in `alembic.ini`)
is what makes `just migrate`, the app and the backend fixture agree about
which database they mean. The backend fixture points `RA2_DATA_DIR` at a temp
directory and runs `alembic upgrade head` against it, so **every migration is
executed on every backend run** (sw-design.md §11.2).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from ra2.infra.config import Settings
from ra2.persistence.models import Base
from ra2.persistence.session import create_engine, ensure_database_dir

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: What `alembic check` and `--autogenerate` compare the database against.
target_metadata = Base.metadata


def _database_url() -> str:
    """`-x url=…` wins, then `RA2_DB_PATH` / `RA2_DATA_DIR` via Settings."""
    override = context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return str(override)
    settings = Settings()
    ensure_database_dir(settings.database_path)
    return settings.database_url


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things; batch mode rewrites the table
        # instead. It needs the named constraints models.py declares.
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """`--sql` mode: emit SQL without a DBAPI connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    """Uses the same engine factory as the app, so the WAL/FK/busy_timeout
    PRAGMAs apply to migrations too."""
    engine = create_engine(_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        # A test or a service already holds a sync connection: reuse it.
        _run(connectable)
        return
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
