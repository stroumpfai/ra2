"""Whether each model could read what it was given travels with its numbers
(`SD48`, risks D1 and D2).

A parse failure and a truncated prompt both score `missing` on every feature
of their record, which is indistinguishable from a model that reads badly
unless the two counts are shown beside the result. They are: on each Results
column header and in the ranking's reported-never-scored group, from the same
rows, through one helper.
"""

import pytest
from tests.fixtures.scored_corpus import ScoredCorpus

from ra2.services.ranking_service import RankingService
from ra2.services.readmodels import ReadingQuality
from ra2.services.results_service import ResultsService

pytestmark = pytest.mark.backend

#: What `scored_with_reading_hazards` put in every run.
EXPECTED = ReadingQuality(extractions=40, parse_failures=2, context_length=4096, at_context_limit=3)


async def test_the_ranking_reports_parse_failures_and_prompts_at_the_limit(
    ranking_service: RankingService, scored_with_reading_hazards: ScoredCorpus
) -> None:
    view = await ranking_service.ranking_tab(scored_with_reading_hazards.evaluation_id)

    assert view.rows
    assert {row.quality for row in view.rows} == {EXPECTED}
    assert EXPECTED.parse_failure_rate == pytest.approx(0.05)


async def test_the_results_columns_carry_the_same_figures(
    results_service: ResultsService,
    ranking_service: RankingService,
    scored_with_reading_hazards: ScoredCorpus,
) -> None:
    """One helper, so the two boards cannot disagree about one run."""
    extraction = await results_service.extraction_tab(scored_with_reading_hazards.evaluation_id)
    ranking = await ranking_service.ranking_tab(scored_with_reading_hazards.evaluation_id)

    by_column = {model.model_id: model.quality for model in extraction.models}
    by_row = {row.model_id: row.quality for row in ranking.rows}
    assert by_column == by_row
    assert set(by_column.values()) == {EXPECTED}


async def test_an_unrecorded_context_is_unknown_never_zero(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    """The positive control, and the direction that matters: a run from before
    `SD48`, or on an Ollama that does not report the context, has no at-limit
    count at all rather than a reassuring `0`."""
    view = await ranking_service.ranking_tab(scored.evaluation_id)

    for row in view.rows:
        assert row.quality is not None
        assert row.quality.context_length is None
        assert row.quality.at_context_limit is None
        assert row.quality.parse_failures == 0
        assert row.quality.extractions == 40
