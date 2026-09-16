"""Tab 1's read model (sw-design.md §16.7).

Suppression is applied **here**, from stored `n` against the evaluation's own
floor (SD19). Two behaviours carry invariants: a suppressed cell is a shape
with no number in it, and suppressed rows sort last in both directions.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ALL_EMPTY, RIGHT_OF_WAY, WEATHER, ScoredCorpus

from ra2.persistence.models import Evaluation
from ra2.services.readmodels import MetricCell, SortDir, SuppressedCell
from ra2.services.results_service import ResultsService


@pytest.mark.asyncio
async def test_the_tab_renders_one_row_per_scored_feature(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    view = await results_service.extraction_tab(scored.evaluation_id)
    names = {row.name for row in view.features.items}
    assert WEATHER in names
    assert "vehicles" in names
    # `s04`: no labelled cases at all, so no row — not an empty one (§8.6).
    assert ALL_EMPTY not in names


@pytest.mark.asyncio
async def test_a_cell_below_the_floor_carries_no_number(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """**mvp-spec.md §11.4 at the service layer.** `SuppressedCell` has no
    `value` field, so the number cannot leak into a renderer by accident."""
    view = await results_service.extraction_tab(scored.evaluation_id)
    row = next(r for r in view.features.items if r.name == RIGHT_OF_WAY)
    assert row.n == 17
    assert row.suppressed is True
    for cell in row.cells.values():
        assert isinstance(cell, SuppressedCell)
        assert cell.n == 17
        assert cell.floor == 20
        assert not hasattr(cell, "value")


@pytest.mark.asyncio
async def test_a_well_populated_cell_carries_its_value_and_interval(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    view = await results_service.extraction_tab(scored.evaluation_id)
    row = next(r for r in view.features.items if r.name == WEATHER)
    assert row.suppressed is False
    for cell in row.cells.values():
        assert isinstance(cell, MetricCell)
        assert cell.ci_low <= cell.value <= cell.ci_high
        assert cell.n == 40


@pytest.mark.asyncio
async def test_lowering_the_floor_unsuppresses_without_a_rescore(
    results_service: ResultsService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**SD19's whole point.** Every cell is computed and stored; suppression
    is a read-time rule. That is what makes §11.4's "configurable per
    evaluation" cheap enough to honour as a column."""
    async with db_session_factory() as session:
        evaluation = await session.get(Evaluation, scored.evaluation_id)
        assert evaluation is not None
        evaluation.min_cell_count = 10
        await session.commit()

    view = await results_service.extraction_tab(scored.evaluation_id)
    row = next(r for r in view.features.items if r.name == RIGHT_OF_WAY)
    assert row.suppressed is False, "no re-score was needed"
    assert all(isinstance(cell, MetricCell) for cell in row.cells.values())


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", [SortDir.ASC, SortDir.DESC])
async def test_suppressed_rows_sort_last_in_both_directions(
    results_service: ResultsService, scored: ScoredCorpus, direction: SortDir
) -> None:
    """**R7.** A suppressed row sorting as zero silently ranks the
    least-evidenced feature as the worst-performing one — the opposite of what
    suppression is for."""
    view = await results_service.extraction_tab(
        scored.evaluation_id, sort_key="n", sort_dir=direction, page_size=50
    )
    flags = [row.suppressed for row in view.features.items]
    assert flags[-1] is True, f"suppressed row is not last on {direction}"
    assert flags.count(True) == 1
    assert not any(flags[: len(flags) - 1])


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", [SortDir.ASC, SortDir.DESC])
async def test_suppressed_rows_sort_last_by_name_too(
    results_service: ResultsService, scored: ScoredCorpus, direction: SortDir
) -> None:
    view = await results_service.extraction_tab(
        scored.evaluation_id, sort_key="name", sort_dir=direction, page_size=50
    )
    assert view.features.items[-1].suppressed is True


@pytest.mark.asyncio
async def test_the_tab_paginates(results_service: ResultsService, scored: ScoredCorpus) -> None:
    view = await results_service.extraction_tab(scored.evaluation_id, page=1, page_size=2)
    assert len(view.features.items) == 2
    assert view.features.total >= 3


@pytest.mark.asyncio
async def test_the_descriptor_carries_the_identity_every_tab_needs(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """ "A score without its config is not a result" (design README)."""
    view = await results_service.extraction_tab(scored.evaluation_id)
    assert view.descriptor.evaluation_id == scored.evaluation_id
    assert view.descriptor.model_count == 2
    assert view.descriptor.min_cell_count == 20
    assert view.descriptor.is_dev is False


@pytest.mark.asyncio
async def test_the_breakdown_carries_stored_counts_not_derived_ones(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """SD18: hit/wrong/missing are stored rows, not back-derived from P and R
    — which is off by one exactly at small `n`."""
    view = await results_service.extraction_tab(
        scored.evaluation_id, expanded_feature_id=scored.feature_ids[WEATHER]
    )
    assert view.breakdown is not None
    assert len(view.breakdown.rows) == 2
    for row in view.breakdown.rows:
        assert row.hit + row.wrong + row.missing == 40
        assert 0.0 <= row.precision <= 1.0


@pytest.mark.asyncio
async def test_the_by_language_card_splits_the_feature(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """mvp-spec.md §13 requires the language breakdown; the fixture's corpus is
    a third French, with its accents already eaten upstream (`s05`)."""
    view = await results_service.by_language(scored.run_ids[0], scored.feature_ids[WEATHER])
    assert {row.language for row in view.rows} == {"de", "fr"}
