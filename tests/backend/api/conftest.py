"""Fixtures shared by `tests/backend/api/{deliveries,corpora}/**` (C1, Wave 3).

The app under test is the real composition root, `create_app()`, wired to a
real migrated temp-file SQLite database (`tests/backend/conftest.py`'s
`db_session_factory`) and driven only through `httpx.ASGITransport` — no
NiceGUI (`mount_ui=False`), no network (sw-design.md §11.2).

`InlineTaskRunner` makes `POST .../analyse` finish its work before the
response comes back, so a router test asserts on state directly rather than
polling `GET /api/v1/tasks/{id}` — that endpoint is C2's, not exercised here.

Owned solely by C1: both `tests/backend/api/deliveries/**` and
`tests/backend/api/corpora/**` are this agent's paths (CONTRACTS.md), so one
shared conftest for both is not a cross-agent conflict.
"""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.infra.config import Settings
from ra2.infra.filestore import HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import SeededFactory
from ra2.infra.tasks import InlineTaskRunner

__all__ = [
    "api_app",
    "api_client",
    "api_host_path_store",
    "api_ids",
    "api_task_runner",
    "api_upload_store",
    "hazard_bytes",
    "hazards_dir",
]

#: `tests/backend/api/` -> `tests/`
_TESTS_ROOT = Path(__file__).resolve().parents[2]
_HAZARDS = _TESTS_ROOT / "fixtures" / "deliveries" / "hazards"


@pytest.fixture
def hazards_dir() -> Path:
    """The twelve committed hazard fixtures (sw-design.md §11.4)."""
    return _HAZARDS


@pytest.fixture
def hazard_bytes(hazards_dir: Path) -> Callable[[str, str], bytes]:
    """One committed hazard file, verbatim. Binary — never a text-mode read."""

    def _read(hazard: str, filename: str) -> bytes:
        return (hazards_dir / hazard / filename).read_bytes()

    return _read


@pytest.fixture
def api_ids() -> SeededFactory:
    return SeededFactory(seed=20260909)


@pytest.fixture
def api_task_runner(api_ids: SeededFactory) -> InlineTaskRunner:
    """Synchronous: by the time a request handler returns, the work is done."""
    return InlineTaskRunner(api_ids)


@pytest.fixture
def api_upload_store(run_upgrade_head: Settings) -> UploadedFileStore:
    return UploadedFileStore(
        run_upgrade_head.deliveries_dir, max_bytes=run_upgrade_head.max_upload_bytes
    )


@pytest.fixture
def api_host_path_store() -> HostPathFileStore:
    return HostPathFileStore()


@pytest.fixture
def api_app(
    app_factory: Callable[..., FastAPI],
    db_session_factory: async_sessionmaker[AsyncSession],
    api_task_runner: InlineTaskRunner,
    api_upload_store: UploadedFileStore,
    api_host_path_store: HostPathFileStore,
    api_ids: SeededFactory,
) -> FastAPI:
    """The real composition root. `census_materialiser` and `language_detector`
    are left at their `create_app()` defaults — the real, production ones —
    since a freeze through the API must exercise the whole seam, not a double.
    """
    return app_factory(
        session_factory=db_session_factory,
        ids=api_ids,
        task_runner=api_task_runner,
        upload_store=api_upload_store,
        host_path_store=api_host_path_store,
        mount_ui=False,
    )


@pytest_asyncio.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """No network at all: `ASGITransport` calls the app in-process (J6)."""
    async with (
        api_app.router.lifespan_context(api_app),
        httpx.AsyncClient(transport=httpx.ASGITransport(api_app), base_url="http://test") as client,
    ):
        yield client
