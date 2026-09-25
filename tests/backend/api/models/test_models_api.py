"""`GET /api/v1/models` through `httpx.ASGITransport` (K2, Wave 3).

Exit criterion (plan-phase-3.md §9): an unreachable endpoint is **200 with
`reachable: false`**, never a 502 — the UI renders the reason beside the
endpoint line and disables Launch (C3), and an error status would force
exactly the toast the design rejects.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import (
    DEFAULT_MODELS,
    StaticEndpointProber,
    StaticModelCatalog,
)

from ra2.domain.ids import QualificationId
from ra2.domain.llm import EndpointStatus, ProbeCode, ProbeResult
from ra2.domain.qualification import Qualification, QualitySummary
from ra2.infra.config import Settings
from ra2.persistence.repositories.qualification_repo import QualificationRepository
from ra2.persistence.session import session_scope
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


# ===========================================================================
# POST /api/v1/models/test — the settings dialog's connection test
# ===========================================================================
#
# The API and the UI are two adapters over one set of services (sw-design.md
# §1.1), so the probe the dialog calls in-process is reachable here too — which
# is also what lets these outcomes be pinned without a browser.


async def test_test_connection_reports_ok(
    api_client: AsyncClient, api_endpoint_prober: StaticEndpointProber
) -> None:
    resp = await api_client.post(
        "/api/v1/models/test", json={"endpoint": "http://127.0.0.1:11434/v1"}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == ProbeCode.OK.value
    assert body["ok"] is True
    assert body["endpoint"] == "http://127.0.0.1:11434/v1"
    assert api_endpoint_prober.probe_calls == 1


async def test_test_connection_probes_the_endpoint_in_the_body(
    api_client: AsyncClient, api_endpoint_prober: StaticEndpointProber
) -> None:
    """Not the configured one. The whole point is to check a value that is not
    configured anywhere yet."""
    await api_client.post("/api/v1/models/test", json={"endpoint": "http://localhost:9999/v1"})

    assert [url for url, _ in api_endpoint_prober.calls] == ["http://localhost:9999/v1"]


async def test_test_connection_uses_the_configured_timeout_when_omitted(
    api_client: AsyncClient, api_endpoint_prober: StaticEndpointProber, backend_settings: Settings
) -> None:
    await api_client.post("/api/v1/models/test", json={"endpoint": "http://127.0.0.1:11434/v1"})

    assert [timeout for _, timeout in api_endpoint_prober.calls] == [backend_settings.llm_timeout_s]


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(ProbeResult(code=ProbeCode.REFUSED_NOT_LOOPBACK), id="not-loopback"),
        pytest.param(ProbeResult(code=ProbeCode.MALFORMED_URL), id="malformed"),
        pytest.param(ProbeResult(code=ProbeCode.CONNECTION_REFUSED), id="refused"),
        pytest.param(ProbeResult(code=ProbeCode.TIMEOUT), id="timeout"),
        pytest.param(ProbeResult(code=ProbeCode.HTTP_ERROR, http_status=404), id="http"),
        pytest.param(ProbeResult(code=ProbeCode.BAD_PAYLOAD), id="payload"),
    ],
)
async def test_every_failure_is_200_not_an_error_status(
    api_client: AsyncClient, api_endpoint_prober: StaticEndpointProber, result: ProbeResult
) -> None:
    """**The exit criterion for this route.** Every outcome is 200.

    The same reasoning that makes an unreachable endpoint `200` with
    `reachable: false` on `GET /models`: a probe that found nothing has
    succeeded at its job. A 4xx or 5xx would make the dialog render the most
    useful answers it can give — "that host is not local", "nothing is
    listening" — as failures of the request itself.
    """
    api_endpoint_prober.set_result(result)

    resp = await api_client.post(
        "/api/v1/models/test", json={"endpoint": "http://192.168.1.5:11434/v1"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == result.code.value
    assert resp.json()["ok"] is False


async def test_a_non_loopback_endpoint_is_not_rejected_by_the_schema(
    api_client: AsyncClient, api_endpoint_prober: StaticEndpointProber
) -> None:
    """`endpoint` is a free string on purpose.

    Validating it into a loopback URL at the schema would turn the single most
    interesting result — "you typed a LAN address" — into a 422 the dialog
    cannot render, and move the N1 decision out of the one place that owns it.
    """
    api_endpoint_prober.set_result(ProbeResult(code=ProbeCode.REFUSED_NOT_LOOPBACK))

    resp = await api_client.post("/api/v1/models/test", json={"endpoint": "http://evil.test/v1"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == ProbeCode.REFUSED_NOT_LOOPBACK.value


async def test_test_connection_does_not_ask_the_catalogue(
    api_client: AsyncClient, api_model_catalog: StaticModelCatalog
) -> None:
    """Reachability is re-checked on view load and on refresh, never as a side
    effect of something else (C3)."""
    await api_client.post("/api/v1/models/test", json={"endpoint": "http://127.0.0.1:11434/v1"})

    assert api_model_catalog.reachable_calls == 0


async def test_models_api_carries_the_qualification(
    api_client: AsyncClient, db_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """SD40: the card's third line, over the wire. A measured model carries
    its numbers and state; an unmeasured one carries `null`, never zeros."""
    measured = DEFAULT_MODELS[0]
    async with session_scope(db_session_factory) as session:
        await QualificationRepository(session).add(
            QualificationId("q-1"),
            Qualification(
                model_tag=measured.tag,
                model_digest=measured.digest,
                ollama_version="0.34.0",
                gpu_name=None,
                ra2_version=None,
                measured_at=datetime(2026, 9, 25, 10, 0, tzinfo=UTC),
                seed_records=200,
                quality=QualitySummary(
                    records=200,
                    reasoning_effort="none",
                    macro_f1=0.895,
                    macro_f1_low=0.870,
                    macro_f1_high=0.905,
                    f1_by_language={"de": 0.91},
                    median_latency_ms=1710,
                    ms_per_record=1745.0,
                    median_completion_tokens=121,
                    entity_fill=0.0,
                    parse_failures=0,
                ),
            ),
        )

    resp = await api_client.get("/api/v1/models")

    assert resp.status_code == 200, resp.text
    by_tag = {m["tag"]: m for m in resp.json()["models"]}
    assert by_tag[measured.tag]["qualification"] == {
        "state": "qualified",
        "measured_digest": measured.digest,
        "seed_macro_f1": 0.895,
        "ms_per_record": 1745.0,
        "entity_fill": 0.0,
        "parallel_calls": 1,
        "launch_ms_per_record": 1745.0,
        "estimated_ms": None,
    }
    assert by_tag[DEFAULT_MODELS[1].tag]["qualification"] is None
