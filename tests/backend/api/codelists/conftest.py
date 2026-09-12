"""Layer 2 fixtures for `/api/v1/codelists/*`: a real app over a real
migrated SQLite database, driven through `httpx.ASGITransport` — no network
(§12.9, sw-design.md §11.2).

Reuses `tests/backend/conftest.py`'s `run_upgrade_head`/`db_session_factory`
and `tests/conftest.py`'s `frozen_clock`/`seeded_ids`, the same way
`tests/backend/api/census/conftest.py` (C2) does — its own independent way to
build the app, owned solely by this router's tests
(`tests/backend/api/codelists/**`, CONTRACTS.md).

`InlineTaskRunner` makes `POST .../analyse` finish before the response comes
back, so a corpus can be seeded through the delivery/corpus API in a single
`await` chain without polling `GET /api/v1/tasks/{id}` (that endpoint is
C2's, not exercised here) — same idiom as `tests/backend/api/corpora/**`.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.conftest import FrozenClock, SeededFactory

from ra2.infra.config import Settings
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app

__all__ = ["api_client"]


@pytest_asyncio.fixture
async def api_client(
    run_upgrade_head: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
    seeded_ids: SeededFactory,
) -> AsyncIterator[AsyncClient]:
    """An `AsyncClient` over a real app, real migrated DB, `mount_ui=False`."""
    app = create_app(
        settings=run_upgrade_head,
        session_factory=db_session_factory,
        clock=frozen_clock,
        ids=seeded_ids,
        task_runner=InlineTaskRunner(seeded_ids),
        mount_ui=False,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
