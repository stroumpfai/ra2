"""`GET /api/v1/tasks/{id}` — thin translation over `TaskRunner.progress`
(sw-design.md §9), driven end-to-end through `httpx.ASGITransport`.

`TaskRunner.submit()` has no HTTP counterpart in phase 1 (analyse/freeze
submit internally); these tests call `task_runner.submit()` directly — the
same object `create_app()` wired onto `app.state.task_runner` — and observe
its progress purely through the HTTP endpoint this router owns.
"""

import asyncio

import pytest
from httpx import AsyncClient

from ra2.domain.ids import TaskId
from ra2.infra.tasks import AsyncioTaskRunner, ProgressReporter, TaskStatus

pytestmark = pytest.mark.backend


async def _poll_until_terminal(
    api_client: AsyncClient, task_id: TaskId, *, attempts: int = 200
) -> dict[str, object]:
    body: dict[str, object] = {}
    for _ in range(attempts):
        response = await api_client.get(f"/api/v1/tasks/{task_id}")
        body = response.json()
        if body["status"] in (TaskStatus.OK.value, TaskStatus.FAILED.value):
            return body
        await asyncio.sleep(0)
    return body


async def test_task_progress_is_observable_from_submit_to_ok(
    api_client: AsyncClient, task_runner: AsyncioTaskRunner
) -> None:
    release = asyncio.Event()

    async def work(reporter: ProgressReporter) -> None:
        reporter.report(0, 2, "starting")
        await release.wait()
        reporter.report(2, 2, "done")

    task_id = task_runner.submit("census-materialise", work)

    # Caught mid-flight: the work is blocked on `release`, so this cannot yet
    # be terminal.
    response = await api_client.get(f"/api/v1/tasks/{task_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["name"] == "census-materialise"
    assert body["status"] in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
    assert body["done"] == 0
    assert body["error"] is None

    release.set()
    body = await _poll_until_terminal(api_client, task_id)

    assert body["status"] == TaskStatus.OK.value
    assert body["done"] == 2
    assert body["total"] == 2
    assert body["message"] == "done"
    assert body["error"] is None


async def test_task_progress_reports_a_failure_as_a_terminal_state(
    api_client: AsyncClient, task_runner: AsyncioTaskRunner
) -> None:
    async def work(reporter: ProgressReporter) -> None:
        reporter.report(0, 1, "starting")
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    task_id = task_runner.submit("broken-task", work)

    body = await _poll_until_terminal(api_client, task_id)

    assert body["status"] == TaskStatus.FAILED.value
    assert body["error"] == "boom"


async def test_get_task_unknown_id_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/tasks/does-not-exist")

    assert response.status_code == 404
