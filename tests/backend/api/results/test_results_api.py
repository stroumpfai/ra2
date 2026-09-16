"""`/api/v1/.../results` and the scoring endpoints (U1, plan-phase-4.md §9).

Two things this layer is responsible for and nothing below it can guarantee:
an unscored run is a **state**, not an error; and a suppressed cell never
leaves the process as a number.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import RIGHT_OF_WAY, WEATHER, ScoredCorpus

from ra2.domain.extraction import RunStatus
from ra2.persistence.models import Run


@pytest.mark.asyncio
async def test_an_unscored_run_is_200_with_scored_false(
    api_client: AsyncClient, unscored: ScoredCorpus
) -> None:
    """**Never a 404** (§16.7).

    The UI renders a state, and an error status would force exactly the toast
    the design rejects — the same reasoning §15.5 applied to an unreachable
    endpoint, and the same shape `GET /api/v1/models` already has.
    """
    response = await api_client.get(f"/api/v1/evaluations/{unscored.evaluation_id}/results")
    assert response.status_code == 200
    assert response.json()["scored"] is False


@pytest.mark.asyncio
async def test_a_scored_run_reports_scored_true(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/results")
    assert response.status_code == 200
    body = response.json()
    assert body["scored"] is True
    assert body["features"]["total"] >= 3


@pytest.mark.asyncio
async def test_an_unknown_evaluation_is_404(api_client: AsyncClient) -> None:
    """*That* is genuinely absent, and 404 is the honest answer for it."""
    response = await api_client.get("/api/v1/evaluations/no-such-eval/results")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_suppressed_cell_never_serialises_a_number(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """**mvp-spec.md §11.4, at the JSON layer.**

    Four layers, four chances to leak a number nobody measured. A client that
    forgets to check `suppressed` must get `null`, not a plausible figure —
    so `value`, `ci_low` and `ci_high` are all absent, and `n` and `floor` are
    present so the notice can be rendered from data.
    """
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/results",
        params={"page_size": 50},
    )
    rows = {row["name"]: row for row in response.json()["features"]["items"]}
    suppressed_row = rows[RIGHT_OF_WAY]
    assert suppressed_row["suppressed"] is True
    assert suppressed_row["n"] == 17
    for cell in suppressed_row["cells"].values():
        assert cell["suppressed"] is True
        assert cell["value"] is None
        assert cell["ci_low"] is None
        assert cell["ci_high"] is None
        assert cell["n"] == 17
        assert cell["floor"] == 20


@pytest.mark.asyncio
async def test_a_scored_cell_carries_its_value_interval_and_mark(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/results", params={"page_size": 50}
    )
    rows = {row["name"]: row for row in response.json()["features"]["items"]}
    for cell in rows[WEATHER]["cells"].values():
        assert cell["suppressed"] is False
        assert cell["ci_low"] <= cell["value"] <= cell["ci_high"]
        assert cell["mark"] in {"best", "tied", "none"}


@pytest.mark.asyncio
async def test_suppressed_rows_sort_last_over_the_wire(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """R7 survives serialisation and paging, in both directions."""
    for direction in ("asc", "desc"):
        response = await api_client.get(
            f"/api/v1/evaluations/{scored.evaluation_id}/results",
            params={"sort_key": "n", "sort_dir": direction, "page_size": 50},
        )
        flags = [row["suppressed"] for row in response.json()["features"]["items"]]
        assert flags[-1] is True, direction


@pytest.mark.asyncio
async def test_the_descriptor_travels_with_every_tab(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """ "A score without its config is not a result", including on the wire."""
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/results")
    descriptor = response.json()["descriptor"]
    assert descriptor["evaluation_id"] == scored.evaluation_id
    assert descriptor["min_cell_count"] == 20
    assert descriptor["is_dev"] is False
    assert descriptor["model_count"] == 2


@pytest.mark.asyncio
async def test_the_breakdown_endpoint_returns_stored_counts(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}"
        f"/results/{scored.feature_ids[WEATHER]}/breakdown"
    )
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 2
    for row in rows:
        assert row["hit"] + row["wrong"] + row["missing"] == 40


@pytest.mark.asyncio
async def test_the_by_language_endpoint_splits_the_feature(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}"
        f"/results/{scored.feature_ids[WEATHER]}/by-language",
        params={"model_id": scored.run_ids[0]},
    )
    assert response.status_code == 200
    assert {row["language"] for row in response.json()["rows"]} == {"de", "fr"}


@pytest.mark.asyncio
async def test_scoring_status_reports_each_run(
    api_client: AsyncClient, unscored: ScoredCorpus
) -> None:
    """The three states §16.7 insists must not share a rendering."""
    response = await api_client.get(f"/api/v1/evaluations/{unscored.evaluation_id}/scoring-status")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    for status in body:
        assert status["is_scored"] is False
        assert status["is_scoreable"] is True, "there are labelled features to score"
        assert status["scored_features"] == 0


@pytest.mark.asyncio
async def test_rescoring_a_scored_run_is_accepted(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.post(f"/api/v1/runs/{scored.run_ids[0]}/rescore")
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_rescoring_a_failed_run_is_409(
    api_client: AsyncClient,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Not a 500 and not a silent no-op: a partial corpus produces
    real-looking numbers over an unstated denominator (§16.1)."""
    async with db_session_factory() as session:
        run = await session.get(Run, scored.run_ids[0])
        assert run is not None
        run.status = RunStatus.FAILED
        await session.commit()

    response = await api_client.post(f"/api/v1/runs/{scored.run_ids[0]}/rescore")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_rescoring_an_unknown_run_is_404(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/runs/no-such-run/rescore")
    assert response.status_code == 404
