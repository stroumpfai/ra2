"""`POST /api/v1/runs/{id}/resume` against a genuinely interrupted run.

A dedicated file: `api_llm_client` is overridden here to fail its first three
calls, which is `run_service.py`'s own `_MAX_CONSECUTIVE_ENDPOINT_ERRORS`
bound — an override that must not leak into `test_runs_api.py`'s other tests,
which all assume the default never-fails double.
"""

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from tests.backend.api.evaluations.conftest import FITTING_MODEL
from tests.fixtures.fake_llm import DEFAULT_ENDPOINT, FakeLLMClient

from ra2.domain.llm import EndpointStatus
from ra2.infra.ollama_client import LlmEndpointError


@pytest.fixture
def api_llm_client() -> FakeLLMClient:
    """Fails call 0 — the worker's bound before a run has committed anything
    is **one**. A launch over four records is therefore interrupted with
    nothing committed, and Resume (continuing the call count on the same
    instance) succeeds on every record.

    This used to fail calls 0, 1 and 2, because the bound used to be three
    whatever the run had done. `_MAX_ENDPOINT_ERRORS_BEFORE_FIRST_ROW` is why
    it is one now: a run that has never produced a row has no evidence the
    configuration works, and at a 600 s timeout three of them is half an hour
    spent re-learning what the first said.
    """
    failure = LlmEndpointError(DEFAULT_ENDPOINT, EndpointStatus.UNREACHABLE)
    return FakeLLMClient(failures={0: failure})


async def test_resume_an_interrupted_run_finishes_it(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(models=(FITTING_MODEL,), record_count=4)
    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")
    assert resp.status_code == 200, resp.text

    listed = await api_client.get("/api/v1/runs", params={"evaluation_id": seeded["evaluation_id"]})
    run = listed.json()["items"][0]
    assert run["status"] == "interrupted"
    assert run["records_done"] == 0

    resp = await api_client.post(f"/api/v1/runs/{run['run_id']}/resume")

    assert resp.status_code == 200, resp.text
    assert resp.json()["task_id"]

    resp = await api_client.get(f"/api/v1/runs/{run['run_id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["records_done"] == 4
