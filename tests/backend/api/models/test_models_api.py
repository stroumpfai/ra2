"""`GET /api/v1/models` through `httpx.ASGITransport` (K2, Wave 3).

Exit criterion (plan-phase-3.md §9): an unreachable endpoint is **200 with
`reachable: false`**, never a 502 — the UI renders the reason beside the
endpoint line and disables Launch (C3), and an error status would force
exactly the toast the design rejects.
"""

from httpx import AsyncClient
from tests.fixtures.fake_llm import DEFAULT_MODELS, StaticModelCatalog

from ra2.domain.llm import EndpointStatus
from ra2.services.evaluation_service import CONNECTION_REASON_UNREACHABLE


async def test_list_models_reachable(
    api_client: AsyncClient, api_model_catalog: StaticModelCatalog
) -> None:
    resp = await api_client.get("/api/v1/models")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connection"]["reachable"] is True
    assert body["connection"]["status"] == "reachable"
    assert body["connection"]["reason"] is None
    # The design's host: an RTX 4090 (24 GB) fits two of the three fixture
    # models and not the third (`tests/conftest.py`'s `static_gpu`/`FIXTURE_GPU`,
    # mirrored in `_seed.py`).
    by_tag = {m["tag"]: m for m in body["models"]}
    assert set(by_tag) == {m.tag for m in DEFAULT_MODELS}
    assert by_tag[DEFAULT_MODELS[0].tag]["fits_vram"] is True
    assert by_tag[DEFAULT_MODELS[2].tag]["fits_vram"] is False
    assert api_model_catalog.reachable_calls >= 1


async def test_list_models_unreachable_is_200_not_502(
    api_client: AsyncClient, api_model_catalog: StaticModelCatalog
) -> None:
    api_model_catalog.set_status(EndpointStatus.UNREACHABLE)

    resp = await api_client.get("/api/v1/models")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connection"]["reachable"] is False
    assert body["connection"]["status"] == "unreachable"
    assert body["connection"]["reason"] == CONNECTION_REASON_UNREACHABLE
    assert body["models"] == []


async def test_list_models_refresh_rechecks_reachability(
    api_client: AsyncClient, api_model_catalog: StaticModelCatalog
) -> None:
    """ "Re-checked on view load and when refresh is pressed" (C3): the
    endpoint coming back between two calls is visible on the very next one,
    with no cache in the way."""
    api_model_catalog.set_status(EndpointStatus.UNREACHABLE)
    first = await api_client.get("/api/v1/models")
    assert first.json()["connection"]["reachable"] is False

    api_model_catalog.set_status(EndpointStatus.REACHABLE)
    second = await api_client.get("/api/v1/models", params={"refresh": "true"})

    assert second.status_code == 200
    assert second.json()["connection"]["reachable"] is True
    assert len(second.json()["models"]) == len(DEFAULT_MODELS)
