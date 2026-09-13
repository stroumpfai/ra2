"""`/api/v1/evaluations/*` through `httpx.ASGITransport` (K2, Wave 3).

Exit criteria (plan-phase-3.md §9): launching with an unfrozen config is 422
and creates nothing; editing a launched evaluation is 409; every endpoint is
exercised through `ASGITransport`, no live socket anywhere.

`EvaluationService`'s own launch-validation logic (the seven
`FeatureValidationError` causes, the codelist gates) is I2's test suite's job
(`tests/backend/services/evaluation/**`) — these tests assert the router's
own translation: status codes, response shapes, and "nothing was created".
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from tests.backend.api.evaluations.conftest import FITTING_MODEL

from ra2.services.evaluation_service import (
    EVAL_ERROR_CONFIG_NOT_FROZEN,
    EVAL_ERROR_NO_MODELS_SELECTED,
    EVAL_ERROR_NO_TEMPLATE,
)


async def test_save_draft_creates_a_row(
    api_client: AsyncClient,
    seed_corpus: Callable[..., Awaitable[str]],
    create_feature_config: Callable[..., Awaitable[str]],
) -> None:
    corpus_id = await seed_corpus()
    config_id = await create_feature_config()

    resp = await api_client.post(
        "/api/v1/evaluations",
        json={"name": "Weather eval", "corpus_id": corpus_id, "feature_config_id": config_id},
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Weather eval"
    assert body["corpus_id"] == corpus_id
    assert body["feature_config_id"] == config_id
    assert body["launched_at"] is None
    assert body["selected_models"] == []
    # The design's defaults (sw-design.md §15.2).
    assert body["temperature"] == 0.0
    assert body["seed"] == 42
    assert body["size"] == "full"


async def test_save_draft_unknown_corpus_is_404(
    api_client: AsyncClient, create_feature_config: Callable[..., Awaitable[str]]
) -> None:
    config_id = await create_feature_config()
    resp = await api_client.post(
        "/api/v1/evaluations",
        json={"name": "x", "corpus_id": "no-such-corpus", "feature_config_id": config_id},
    )
    assert resp.status_code == 404


async def test_list_evaluations(
    api_client: AsyncClient,
    seed_corpus: Callable[..., Awaitable[str]],
    create_feature_config: Callable[..., Awaitable[str]],
) -> None:
    corpus_id = await seed_corpus()
    config_id = await create_feature_config()
    for name in ("First", "Second"):
        resp = await api_client.post(
            "/api/v1/evaluations",
            json={"name": name, "corpus_id": corpus_id, "feature_config_id": config_id},
        )
        assert resp.status_code == 201, resp.text

    resp = await api_client.get("/api/v1/evaluations")

    assert resp.status_code == 200
    names = {row["name"] for row in resp.json()}
    assert names == {"First", "Second"}


async def test_get_evaluation_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/evaluations/no-such-id")
    assert resp.status_code == 404


async def test_get_evaluation_shape(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(models=(FITTING_MODEL,))

    resp = await api_client.get(f"/api/v1/evaluations/{seeded['evaluation_id']}")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["draft"]["evaluation_id"] == seeded["evaluation_id"]
    assert body["connection"]["reachable"] is True
    assert {m["tag"] for m in body["models"]}.issuperset({FITTING_MODEL})
    assert body["can_launch"] is True
    assert body["runs"] == {
        "items": [],
        "meta": {
            "total": 0,
            "page": 1,
            "page_size": 25,
            "sort_key": "started_at",
            "sort_dir": "desc",
        },
    }
    assert body["provenance"] is None


async def test_update_draft(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready()

    resp = await api_client.put(
        f"/api/v1/evaluations/{seeded['evaluation_id']}",
        json={"selected_models": [FITTING_MODEL], "temperature": 0.5, "seed": 7},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["selected_models"] == [FITTING_MODEL]
    assert body["temperature"] == 0.5
    assert body["seed"] == 7


async def test_update_draft_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.put("/api/v1/evaluations/no-such-id", json={"name": "x"})
    assert resp.status_code == 404


async def test_launch_unfrozen_config_is_422_and_creates_nothing(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(frozen=False, models=(FITTING_MODEL,))

    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")

    assert resp.status_code == 422, resp.text
    body = resp.json()
    # "Notes" is `create_feature_config`'s default name (`_seed.py`).
    assert body["validation_errors"] == [EVAL_ERROR_CONFIG_NOT_FROZEN.format(name="Notes")]

    # Nothing was created: the draft is still unlaunched and has no runs.
    resp = await api_client.get(f"/api/v1/evaluations/{seeded['evaluation_id']}")
    assert resp.status_code == 200
    ev = resp.json()
    assert ev["draft"]["launched_at"] is None
    assert ev["runs"]["meta"]["total"] == 0


async def test_launch_no_template_is_422(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(template=False, models=(FITTING_MODEL,))

    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")

    assert resp.status_code == 422, resp.text
    assert resp.json()["validation_errors"] == [EVAL_ERROR_NO_TEMPLATE]


async def test_launch_no_models_selected_is_422(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready()  # template + frozen config, no models selected

    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")

    assert resp.status_code == 422, resp.text
    assert resp.json()["validation_errors"] == [EVAL_ERROR_NO_MODELS_SELECTED]


async def test_launch_success_returns_task_id_and_runs_to_completion(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(models=(FITTING_MODEL,), record_count=2)

    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_id"]
    assert body["evaluation"]["draft"]["launched_at"] is not None
    assert body["evaluation"]["can_launch"] is False

    # `InlineTaskRunner` ran the submitted job to completion before the
    # `POST .../launch` response above came back; a fresh GET now sees it.
    resp = await api_client.get(f"/api/v1/evaluations/{seeded['evaluation_id']}")
    assert resp.status_code == 200
    ev = resp.json()
    assert ev["runs"]["meta"]["total"] == 1
    assert ev["runs"]["items"][0]["model_tag"] == FITTING_MODEL
    assert ev["runs"]["items"][0]["status"] == "done"
    assert ev["progress"][0]["done"] == 2
    assert ev["progress"][0]["total"] == 2
    assert ev["provenance"] is not None
    assert ev["provenance"]["model_name"] == FITTING_MODEL


async def test_launch_twice_is_409(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(models=(FITTING_MODEL,))
    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")
    assert resp.status_code == 200, resp.text

    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")

    assert resp.status_code == 409


async def test_update_after_launch_is_409(
    api_client: AsyncClient, seed_ready: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    seeded = await seed_ready(models=(FITTING_MODEL,))
    resp = await api_client.post(f"/api/v1/evaluations/{seeded['evaluation_id']}/launch")
    assert resp.status_code == 200, resp.text

    resp = await api_client.put(
        f"/api/v1/evaluations/{seeded['evaluation_id']}", json={"name": "renamed"}
    )

    assert resp.status_code == 409
