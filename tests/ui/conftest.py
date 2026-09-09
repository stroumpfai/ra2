"""Layer-3 fixtures — NiceGUI's in-process `User`, no browser.

Owned by A5 (sw-design.md §11.3). The root `tests/conftest.py` is frozen and
carries nothing NiceGUI-specific, so the simulation lives here (X4).

The app under test is built by the **real composition root**: `create_app()`
with `mount_ui=True` and the deterministic adapters the root `app_factory`
injects. There is no test-mode branch in production code (§12.12); `mount_ui`
is a composition-root parameter, exactly as CONTRACTS.md M0-D6 describes it.

`nicegui_reset_globals()` is NiceGUI's own teardown for its process-wide
singleton (`nicegui.core.app`): it drops routes, middleware and client state
between tests, which is what lets more than one UI-mounted app exist in one
pytest session.

**The database is migrated first.** From M6 the Import view reads its delivery
and its corpora from real services, so every UI page now needs a schema.
`create_app()` never migrates — `just migrate` does — and §12.10 bans
`metadata.create_all()` in tests as much as in the app, so the schema comes
from the real Alembic chain here, the same way `tests/backend/conftest.py`
gets it. `migrated_db` is **synchronous** on purpose: `migrations/env.py`
calls `asyncio.run`, which cannot re-enter the loop an async fixture is
already running on.
"""

import os
from argparse import Namespace
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from nicegui import ui
from nicegui.functions.download import download
from nicegui.functions.navigate import Navigate
from nicegui.functions.notify import notify
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User

from ra2.infra.config import Settings

__all__ = ["migrated_db", "user"]

#: `tests/ui/conftest.py` -> `tests/ui` -> `tests` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def migrated_db(settings: Settings) -> Settings:
    """A real temp-file SQLite database at `alembic upgrade head`."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "ra2" / "persistence" / "migrations"))
    # Mirrors what `-x url=...` would set from the CLI, exactly as
    # `tests/backend/conftest.py` does.
    config.cmd_opts = Namespace(x=[f"url={settings.database_url}"])
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(config, "head")
    return settings


@pytest.fixture
async def user(app_factory: Callable[..., FastAPI], migrated_db: Settings) -> AsyncIterator[User]:
    """A simulated browser against the real, UI-mounted app."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                yield User(client)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            ui.navigate = Navigate()
            ui.notify = notify
            ui.download = download
