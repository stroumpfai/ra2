"""Layer 2 fixtures for `/api/v1/tasks/{id}`: a real app driven through
`httpx.ASGITransport`, wired to a real `AsyncioTaskRunner` rather than
`InlineTaskRunner` — `InlineTaskRunner` runs a task to completion before
`submit()` even returns, which makes "observe progress from submit to
terminal state" trivial. `AsyncioTaskRunner` schedules the work as a real
`asyncio.Task` on the same loop the test and the ASGI app share, so a task
with a real await point can be caught mid-flight (plan-m0-m5.md §7's C2 exit
criterion).
"""

from collections.abc import AsyncIterator, Callable

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ra2.infra.idgen import SeededFactory
from ra2.infra.tasks import AsyncioTaskRunner

__all__ = ["api_client", "task_runner"]


@pytest_asyncio.fixture
async def task_runner() -> AsyncioTaskRunner:
    return AsyncioTaskRunner(SeededFactory())


@pytest_asyncio.fixture
async def api_client(
    app_factory: Callable[..., FastAPI], task_runner: AsyncioTaskRunner
) -> AsyncIterator[AsyncClient]:
    """`/api/v1/tasks` needs no database — `app_factory`'s defaults (a
    fresh, unmigrated temp SQLite file) are never touched by this router."""
    app = app_factory(task_runner=task_runner)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
