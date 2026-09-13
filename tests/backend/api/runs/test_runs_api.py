"""`/api/v1/runs/*` through `httpx.ASGITransport` (K2, Wave 3).

Reuses the `evaluations` directory's seeding fixtures (`_seed.py`, K2's own
path) to reach a launched evaluation with committed runs — the run worker's
own behaviour (retries, resume mechanics, parse outcomes) is I3's test suite's
job (`tests/backend/services/run/**`); these tests assert the router's own
translation only.
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from tests.backend.api.evaluations.conftest import FITTING_MODEL


async def _launch(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]], **kwargs: object
) -> dict[str, str]:
    seeded = await seed_ready(models=(FITTING_MODEL,), **kwargs)
    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")
    assert resp.status_code == 200, resp.text
    return seeded


async def test_list_runs_for_evaluation(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await _launch(api_client, seed_ready, record_count=2)

    resp = await api_client.get("/api/v1/runs", params={"evaluation_id": seeded["evaluation_id"]})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 10
    assert body["meta"]["sort_key"] == "started_at"
    assert body["meta"]["sort_dir"] == "desc"
    row = body["items"][0]
    assert row["model_tag"] == FITTING_MODEL
    assert row["status"] == "done"
    assert row["records_done"] == 2


async def test_list_runs_for_unknown_evaluation_is_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/runs", params={"evaluation_id": "no-such-evaluation"})
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 0


async def test_get_run(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await _launch(api_client, seed_ready)
    listed = await api_client.get("/api/v1/runs", params={"evaluation_id": seeded["evaluation_id"]})
    run_id = listed.json()["items"][0]["run_id"]

    resp = await api_client.get(f"/api/v1/runs/{run_id}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["evaluation_id"] == seeded["evaluation_id"]
    assert body["status"] == "done"


async def test_get_run_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/runs/no-such-run")
    assert resp.status_code == 404


async def test_get_progress(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await _launch(api_client, seed_ready, record_count=3)
    listed = await api_client.get("/api/v1/runs", params={"evaluation_id": seeded["evaluation_id"]})
    run_id = listed.json()["items"][0]["run_id"]

    resp = await api_client.get(f"/api/v1/runs/{run_id}/progress")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["status"] == "done"
    assert body["done"] == 3
    assert body["total"] == 3
    assert body["percent"] == 100.0


async def test_get_progress_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/runs/no-such-run/progress")
    assert resp.status_code == 404


async def test_resume_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.post("/api/v1/runs/no-such-run/resume")
    assert resp.status_code == 404


async def test_resume_a_done_run_is_a_no_op_success(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await _launch(api_client, seed_ready)
    listed = await api_client.get("/api/v1/runs", params={"evaluation_id": seeded["evaluation_id"]})
    run_id = listed.json()["items"][0]["run_id"]

    resp = await api_client.post(f"/api/v1/runs/{run_id}/resume")

    assert resp.status_code == 200, resp.text
    assert resp.json()["task_id"]
