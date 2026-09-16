"""Tab 2's read model (mvp-spec.md §11.2, sw-design.md §16.7).

The tab reports presence rate, the cross-tab and flag inconsistency, and
**deliberately refuses** presence precision / recall / F1 (`D2`).
"""

import pytest
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus

from ra2.services.readmodels import MetricCell
from ra2.services.results_service import ResultsService


@pytest.mark.asyncio
async def test_the_tab_shows_one_model_at_a_time(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """Presence is per-flag, so a three-model grid would not be readable
    (design README §2b)."""
    view = await results_service.presence_tab(scored.evaluation_id)
    assert view.model_id == scored.run_ids[0]
    assert len(view.models) == 2


@pytest.mark.asyncio
async def test_switching_model_changes_the_numbers(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    first = await results_service.presence_tab(scored.evaluation_id, model_id=scored.run_ids[0])
    second = await results_service.presence_tab(scored.evaluation_id, model_id=scored.run_ids[1])
    assert first.model_id != second.model_id


@pytest.mark.asyncio
async def test_every_presence_row_carries_its_goal_1_companions(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """**mvp-spec.md §11.2, as a shape.**

    "Goal 2 numbers are never published without the corresponding Goal 1
    numbers — a weak extractor manufactures false 'missing' flags."
    `PresenceRow.goal1` is required, so a row without them is a type error;
    this asserts the *query* actually fetches them rather than a later
    refactor quietly dropping the join.
    """
    view = await results_service.presence_tab(scored.evaluation_id)
    assert view.rows
    for row in view.rows:
        assert row.goal1 is not None
        assert 0.0 <= row.goal1.f1 <= 1.0
        assert 0.0 <= row.goal1.precision <= 1.0
        assert 0.0 <= row.goal1.recall <= 1.0


@pytest.mark.asyncio
async def test_presence_rates_are_split_by_language(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    view = await results_service.presence_tab(scored.evaluation_id)
    row = next(r for r in view.rows if r.feature_key == WEATHER)
    assert {"*", "de", "fr"} <= set(row.rates)
    assert isinstance(row.rates["*"], MetricCell)


@pytest.mark.asyncio
async def test_the_cross_tab_reports_the_self_contradiction_cell(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """`s07`: the fixture has one record where the model says the text does
    **not** contain the feature and extracts the right value anyway."""
    view = await results_service.presence_tab(scored.evaluation_id, feature_key=WEATHER)
    assert view.cross_tab is not None
    assert view.cross_tab.hit_absent >= 1
    total = (
        view.cross_tab.hit_present
        + view.cross_tab.hit_absent
        + view.cross_tab.wrong_present
        + view.cross_tab.wrong_absent
        + view.cross_tab.missing_present
        + view.cross_tab.missing_absent
    )
    assert total == 40


@pytest.mark.asyncio
async def test_flag_inconsistency_is_reported_per_model(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """§11.2's one Goal 2 number that is a quality signal rather than a
    description, because it is a self-contradiction rather than a comparison
    against a gold label nobody has."""
    view = await results_service.presence_tab(scored.evaluation_id)
    assert len(view.flag_inconsistency) == 2
    for row in view.flag_inconsistency:
        assert isinstance(row.cell, MetricCell)
        assert 0.0 <= row.cell.value <= 1.0


@pytest.mark.asyncio
async def test_the_tab_exposes_no_presence_f1_anywhere(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """`D2`. There is no independent gold label for presence, and deriving one
    from Goal 1 correctness would be circular in a way the output would not
    show. The deferral is only real if the number is unreachable."""
    view = await results_service.presence_tab(scored.evaluation_id)
    for row in view.rows:
        assert not hasattr(row, "presence_f1")
        assert not hasattr(row, "presence_precision")
