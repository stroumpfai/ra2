"""`DELETE /runs`, `DELETE /evaluations`, `DELETE /deliveries`, and the two
export routes (plan-reset-and-discard.md §2.1, §8).

Thin translation is the whole of these routes, so the tests are about the
**status codes and what survives them**: 409 for each guard, 404 for a key that
is not there, and a body that says what went — because nothing else records it
(§18.3).
"""

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.api.lifecycle.conftest import ScoredApi

from ra2.domain.extraction import RunStatus
from ra2.persistence.models import Evaluation, Extraction, Mismatch, Run, Score

pytestmark = pytest.mark.backend


async def _count(session: AsyncSession, model: type, *where: object) -> int:
    stmt = select(func.count()).select_from(model)
    for clause in where:
        stmt = stmt.where(clause)  # type: ignore[arg-type]
    return int(await session.scalar(stmt) or 0)


# --- preview --------------------------------------------------------------


async def test_run_preview_reports_the_counts(
    api_client: httpx.AsyncClient, scored_api: ScoredApi
) -> None:
    response = await api_client.get(f"/api/v1/runs/{scored_api.tagged_run_id}/discard-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "run"
    assert body["extractions"] > 0
    assert body["tagged_mismatches"] == 1
    assert body["has_exportable"] is True
    assert body["blocked"] is False


async def test_preview_of_a_missing_run_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/runs/nope/discard-preview")
    assert response.status_code == 404


# --- the guards, over the wire --------------------------------------------


async def test_an_active_run_is_409(
    api_client: httpx.AsyncClient,
    scored_api: ScoredApi,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = scored_api.untagged_run_id
    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = RunStatus.RUNNING
        await session.commit()

    response = await api_client.delete(f"/api/v1/runs/{run_id}")

    assert response.status_code == 409
    assert "running" in response.json()["detail"]


async def test_tagged_work_is_409_until_forced(
    api_client: httpx.AsyncClient,
    scored_api: ScoredApi,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = scored_api.tagged_run_id

    refused = await api_client.delete(f"/api/v1/runs/{run_id}")
    assert refused.status_code == 409
    assert "1 tagged" in refused.json()["detail"]
    async with db_session_factory() as session:
        assert await session.get(Run, run_id) is not None

    forced = await api_client.delete(f"/api/v1/runs/{run_id}", params={"force": "true"})
    assert forced.status_code == 200
    body = forced.json()
    assert body["forced"] is True
    assert body["tagged_mismatches"] == 1
    async with db_session_factory() as session:
        assert await session.get(Run, run_id) is None


async def test_the_receipt_names_what_went(
    api_client: httpx.AsyncClient,
    scored_api: ScoredApi,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = scored_api.untagged_run_id
    before = (await api_client.get(f"/api/v1/runs/{run_id}/discard-preview")).json()

    response = await api_client.delete(f"/api/v1/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["extractions"] == before["extractions"]
    assert body["scores"] == before["scores"]
    assert body["forced"] is False
    async with db_session_factory() as session:
        assert await _count(session, Extraction, Extraction.run_id == run_id) == 0
        assert await _count(session, Score, Score.run_id == run_id) == 0
        assert await _count(session, Mismatch, Mismatch.run_id == run_id) == 0


async def test_discarding_an_evaluation_keeps_its_corpus(
    api_client: httpx.AsyncClient,
    scored_api: ScoredApi,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    evaluation_id = scored_api.corpus.evaluation_id

    response = await api_client.delete(
        f"/api/v1/evaluations/{evaluation_id}", params={"force": "true"}
    )

    assert response.status_code == 200
    assert response.json()["runs"] == len(scored_api.corpus.run_ids)
    async with db_session_factory() as session:
        assert await session.get(Evaluation, evaluation_id) is None
    # The corpus it cited is still there and still readable.
    corpus = await api_client.get(f"/api/v1/corpora/{scored_api.corpus.corpus_id}")
    assert corpus.status_code == 200


async def test_discarding_a_missing_evaluation_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.delete("/api/v1/evaluations/nope")
    assert response.status_code == 404


async def test_discarding_a_missing_delivery_is_404(api_client: httpx.AsyncClient) -> None:
    response = await api_client.delete("/api/v1/deliveries/nope")
    assert response.status_code == 404


# --- export before discard ------------------------------------------------


@pytest.mark.parametrize("table", ["scores", "mismatches"])
async def test_the_exports_are_the_house_csv(
    api_client: httpx.AsyncClient, scored_api: ScoredApi, table: str
) -> None:
    """UTF-8 with a BOM, `;`-delimited, a comment line naming the run — the
    conventions §7 settled, reused rather than re-derived."""
    response = await api_client.get(f"/api/v1/runs/{scored_api.tagged_run_id}/{table}.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    first_line = response.content.decode("utf-8-sig").splitlines()[0]
    assert first_line.startswith(f"# run {scored_api.tagged_run_id}")


async def test_the_mismatch_export_carries_the_analyst_tag(
    api_client: httpx.AsyncClient, scored_api: ScoredApi
) -> None:
    response = await api_client.get(f"/api/v1/runs/{scored_api.tagged_run_id}/mismatches.csv")

    text = response.content.decode("utf-8-sig")
    header = text.splitlines()[1]
    assert "analyst_tag" in header.split(";")
    assert "structured_data_error" in text


async def test_exporting_a_missing_run_is_404(api_client: httpx.AsyncClient) -> None:
    assert (await api_client.get("/api/v1/runs/nope/scores.csv")).status_code == 404
