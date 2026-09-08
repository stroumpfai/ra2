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
"""

import os
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.functions.download import download
from nicegui.functions.navigate import Navigate
from nicegui.functions.notify import notify
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User

__all__ = ["user"]


@pytest.fixture
async def user(app_factory: Callable[..., FastAPI]) -> AsyncIterator[User]:
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
