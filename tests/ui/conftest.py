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
gets it: once per session into a template, copied per test
(`tests/fixtures/migrations.py`). `migrated_template` is **synchronous** on
purpose — `migrations/env.py` calls `asyncio.run`, which cannot re-enter the
loop an async fixture is already running on.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.functions.download import download
from nicegui.functions.navigate import Navigate
from nicegui.functions.notify import notify
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from tests.fixtures.migrations import build_template, copy_template

from ra2.infra.config import Settings

__all__ = ["app_factory", "migrated_db", "migrated_template", "user"]


@pytest.fixture
async def app_factory(
    app_factory: Callable[..., FastAPI],
) -> AsyncIterator[Callable[..., FastAPI]]:
    """The root `app_factory`, with the engines it builds disposed at teardown.

    An undisposed aiosqlite engine finalises on the garbage collector's
    schedule, and `filterwarnings = ["error"]` turns that into an error in
    **whichever test happens to be running at the time** — which is what it
    did, as a `ResourceWarning` about a connection "deleted before being
    closed" landing on a test that had nothing to do with it.
    `create_app()` never disposes, correctly: the process owns its engine for
    its lifetime. So whoever built the app has to, and in this layer that is
    every test — `user` below, and the fifteen view-specific fixtures in
    `test_*.py` that mount their own app with their own seeding and their own
    overrides.

    Wrapping the factory rather than patching those fifteen is the difference
    between one place that is right and fifteen that have to stay right.
    `tests/backend/services/run/conftest.py`'s `build_app` already keeps this
    list by hand for the same reason; this is the same list, kept by the
    fixture they all go through.

    Overriding a fixture while requesting the enclosing one of the same name
    is pytest's own idiom for exactly this. The root fixture is frozen
    (CONTRACTS.md) and stays untouched.
    """
    built: list[FastAPI] = []

    def _tracking(**overrides: object) -> FastAPI:
        app = app_factory(**overrides)
        built.append(app)
        return app

    yield _tracking

    # Stop anything still ticking, and let it unwind, **before** the engines
    # go. `dispose()` closes the pool's *idle* connections; a progress tick in
    # flight holds a session, and that session's connection is checked out,
    # which is the one thing dispose cannot reach. Left alone it is finalised
    # by the garbage collector after this loop has closed — `ResourceWarning:
    # … deleted before being closed`, or aiosqlite's worker thread landing
    # `call_soon_threadsafe` on a dead loop — and under
    # `filterwarnings = ["error"]` that is an error in whichever test is
    # running by then.
    #
    # Cancelling rather than waiting is deliberate: a poll over a run that
    # never settles would never finish on its own, and `gather` here is what
    # gives each task the turns it needs to run its `async with` exits and put
    # its connection back while there is still a loop to do it on.
    tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    for app in built:
        await app.state.engine.dispose()


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The real Alembic chain, run once for the whole session."""
    return build_template(tmp_path_factory.mktemp("ui-migrated-template"))


@pytest.fixture
def migrated_db(migrated_template: Path, settings: Settings) -> Settings:
    """A real temp-file SQLite database at head, private to this test."""
    return copy_template(migrated_template, settings)


@pytest.fixture
async def user(app_factory: Callable[..., FastAPI], migrated_db: Settings) -> AsyncIterator[User]:
    """A simulated browser against the real, UI-mounted app.

    The engine is disposed by `app_factory` above, for every app in the layer
    rather than only this one.
    """
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
