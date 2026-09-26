"""`/presence/*` and `/ranking` (U2, plan-phase-4.md §9).

The schema-level guarantee this layer owns: **a presence figure cannot be
serialised without its Goal 1 companions** (mvp-spec.md §11.2). The read model
makes that a type error internally; here it is asserted on the wire, so a
future wire format cannot quietly drop the column the read model is careful to
carry.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus

from ra2.persistence.models import Evaluation
from ra2.services.export_service import CLASSIFICATION_COMMENT, CSV_BOM, CSV_DELIMITER


@pytest.mark.asyncio
async def test_the_presence_tab_serialises(api_client: AsyncClient, scored: ScoredCorpus) -> None:
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/presence")
    assert response.status_code == 200
    body = response.json()
    assert body["scored"] is True
    assert body["model_id"] == scored.run_ids[0]
    assert len(body["models"]) == 2


@pytest.mark.asyncio
async def test_every_presence_row_carries_its_goal_1_companions_on_the_wire(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """**§11.2, at the schema level.**

    "Goal 2 numbers are never published without the corresponding Goal 1
    numbers — a weak extractor manufactures false 'missing' flags."
    `Goal1CompanionResponse` is a required field, so a row without it cannot be
    constructed; this proves the endpoint actually populates it.
    """
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/presence")
    rows = response.json()["rows"]
    assert rows
    for row in rows:
        assert row["goal1"] is not None
        assert set(row["goal1"]) == {"f1", "precision", "recall"}
        assert 0.0 <= row["goal1"]["f1"] <= 1.0


@pytest.mark.asyncio
async def test_the_presence_schema_has_no_presence_f1_field(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """`D2`: deferred pending a human-labelled subset. The deferral is only
    real if the field is unreachable."""
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/presence")
    for row in response.json()["rows"]:
        assert "presence_f1" not in row
        assert "presence_precision" not in row


@pytest.mark.asyncio
async def test_switching_model_changes_the_tab(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/presence",
        params={"model_id": scored.run_ids[1]},
    )
    assert response.json()["model_id"] == scored.run_ids[1]


@pytest.mark.asyncio
async def test_the_cross_tab_and_flag_inconsistency_serialise(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/presence",
        params={"feature_key": WEATHER},
    )
    body = response.json()
    assert body["cross_tab"]["hit_absent"] >= 1, "s07: the self-contradiction case"
    # One row per model — the card exists so the flag can be compared across
    # models (design README §2d).
    assert len(body["flag_inconsistency"]) == 2


@pytest.mark.asyncio
async def test_the_per_record_list_is_paged_and_marks_anonymisation(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """**The actionable form of Goal 2.** `anonymised` is required wherever
    text is shown (mvp-spec.md §13), and this list shows the record's value."""
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/presence/records",
        params={"feature_key": WEATHER, "page_size": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert len(body["items"]) <= 2
    for row in body["items"]:
        assert row["anonymised"] is True
        assert row["record_value"]
        assert "does not say what" in row["finding"]


@pytest.mark.asyncio
async def test_the_csv_export_carries_the_bom_and_the_delimiter(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """The conventions are reused, not re-derived: UTF-8 with a BOM for Excel
    on Windows (N3), `;`-delimited, with a comment line above the header."""
    response = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/presence/records.csv",
        params={"feature_key": WEATHER, "model_id": scored.run_ids[0]},
    )
    assert response.status_code == 200
    assert response.content.startswith(CSV_BOM)
    text = response.content[len(CSV_BOM) :].decode("utf-8")
    assert text.startswith(CLASSIFICATION_COMMENT)
    assert text.splitlines()[1].startswith("# evaluation ")
    header = text.splitlines()[2]
    assert header.split(CSV_DELIMITER)[0] == "record_id"
    assert "anonymised" in header


@pytest.mark.asyncio
async def test_the_csv_row_count_matches_the_rendered_total(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """An export writes the **currently filtered** table (§7). A CSV that
    disagreed with the number printed above it is the failure `P4-D3` avoids
    by handing the exporter the rows rather than a filter to re-run.
    """
    listed = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/presence/records",
        params={"feature_key": WEATHER, "page_size": 100},
    )
    exported = await api_client.get(
        f"/api/v1/evaluations/{scored.evaluation_id}/presence/records.csv",
        params={"feature_key": WEATHER},
    )
    text = exported.content[len(CSV_BOM) :].decode("utf-8")
    data_rows = [line for line in text.splitlines()[3:] if line.strip()]
    assert len(data_rows) == listed.json()["total"]


@pytest.mark.asyncio
async def test_the_ranking_tab_serialises_with_shared_ranks(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/ranking")
    assert response.status_code == 200
    body = response.json()
    assert body["scored"] is True
    assert body["rows"]
    assert min(row["rank"] for row in body["rows"]) == 1
    for row in body["rows"]:
        assert row["best"] + row["tied"] + row["worse"] == body["scored_feature_count"]


@pytest.mark.asyncio
async def test_the_ranking_wire_carries_the_pinned_size_and_never_a_zero(
    api_client: AsyncClient,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**SD41.** `model_size_bytes` replaced `vram_bytes`, which every row
    carried as a hard-coded `0` — a number no client could read a meaning out
    of.

    On the wire the field is the run's pin, and `null` when the run has none:
    the absence has to survive serialisation, or the tab has no way to tell it
    from a measurement.
    """
    from sqlalchemy import update

    from ra2.persistence.models import Run

    body = (await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/ranking")).json()
    assert body["rows"]
    assert all(row["model_size_bytes"] > 0 for row in body["rows"])
    assert all("vram_bytes" not in row for row in body["rows"])

    async with db_session_factory() as session:
        await session.execute(update(Run).values(model_size_bytes=None))
        await session.commit()

    body = (await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/ranking")).json()
    assert all(row["model_size_bytes"] is None for row in body["rows"])


@pytest.mark.asyncio
async def test_the_ranking_matches_the_extraction_tab_over_the_wire(
    api_client: AsyncClient, scored: ScoredCorpus
) -> None:
    """**The §16.5 invariant, through two independent endpoints.**

    "If the two disagree, Ranking is wrong by construction." J13 will assert
    the same thing in the browser; this catches it a layer earlier.
    """
    ranking = (await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/ranking")).json()
    extraction = (
        await api_client.get(
            f"/api/v1/evaluations/{scored.evaluation_id}/results", params={"page_size": 50}
        )
    ).json()

    for row in ranking["rows"]:
        rendered = [
            cell["value"]
            for feature in extraction["features"]["items"]
            if (cell := feature["cells"].get(row["model_id"])) and not cell["suppressed"]
        ]
        assert rendered
        assert row["macro_f1"] == pytest.approx(sum(rendered) / len(rendered), abs=1e-9)


@pytest.mark.asyncio
async def test_an_all_suppressed_run_returns_a_well_formed_payload_not_an_empty_list(
    api_client: AsyncClient,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An empty list is what a UI renders as a blank table, and "no results"
    is a different fact from "not enough data for results" (§16.7)."""
    async with db_session_factory() as session:
        evaluation = await session.get(Evaluation, scored.evaluation_id)
        assert evaluation is not None
        evaluation.min_cell_count = 10_000
        await session.commit()

    response = await api_client.get(f"/api/v1/evaluations/{scored.evaluation_id}/ranking")
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert body["scored_feature_count"] == 0
    assert "could be scored" in body["verdict_headline"]
    assert "10000" in body["verdict_detail"]


@pytest.mark.asyncio
async def test_an_unscored_evaluation_ranks_nothing_without_erroring(
    api_client: AsyncClient, unscored: ScoredCorpus
) -> None:
    response = await api_client.get(f"/api/v1/evaluations/{unscored.evaluation_id}/ranking")
    assert response.status_code == 200
    assert response.json()["scored"] is False
