"""Tab 3's read model (mvp-spec.md §11.5, sw-design.md §16.5).

`design/results/README.md` states the invariant this module exists to keep:
"Every number on this tab is derived from tab 1's scored rows — nothing here is
independent... if the two disagree, Ranking is wrong by construction."

The first test is that invariant, asserted at the service layer. J13 will
assert the same thing in the browser.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus

from ra2.persistence.models import Evaluation
from ra2.services.ranking_service import RankingService
from ra2.services.readmodels import MetricCell
from ra2.services.results_service import ResultsService


@pytest.mark.asyncio
async def test_the_macro_is_the_mean_of_the_rendered_extraction_cells(
    ranking_service: RankingService,
    results_service: ResultsService,
    scored: ScoredCorpus,
) -> None:
    """**The keystone.** Read the macro off tab 3 and the per-feature values
    off tab 1, computed independently, and assert the first is the mean of the
    non-suppressed second."""
    ranking = await ranking_service.ranking_tab(scored.evaluation_id)
    extraction = await results_service.extraction_tab(scored.evaluation_id, page_size=50)

    for row in ranking.rows:
        rendered = [
            cell.value
            for feature in extraction.features.items
            if isinstance(cell := feature.cells.get(row.model_id), MetricCell)
        ]
        assert rendered, "tab 1 rendered no comparable cells for this model"
        expected = sum(rendered) / len(rendered)
        assert row.macro_f1 == pytest.approx(expected, abs=1e-9), (
            f"{row.model_id}: ranking says {row.macro_f1}, tab 1 says {expected}"
        )


@pytest.mark.asyncio
async def test_best_tied_and_worse_sum_to_the_scored_feature_count(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    """A drift there means the marks and the macro were computed from
    different sets — which is exactly the disagreement §16.5 forbids."""
    view = await ranking_service.ranking_tab(scored.evaluation_id)
    for row in view.rows:
        assert row.best + row.tied + row.worse == view.scored_feature_count


@pytest.mark.asyncio
async def test_a_suppressed_feature_is_excluded_from_the_macro_and_the_counts(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    """`s01` has 17 labelled cases. It is stored, rendered as suppressed, and
    takes no part in either aggregate (§16.4)."""
    view = await ranking_service.ranking_tab(scored.evaluation_id)
    # Four labelled features are scored; one of them is below the floor.
    assert view.scored_feature_count == 3
    assert view.unscored_feature_count >= 1


@pytest.mark.asyncio
async def test_tied_models_share_a_rank(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    """§11.5: overlapping intervals are rendered as a tie, **not** as an
    order. Ranks repeat (`1, 1, 3`) and never enumerate."""
    view = await ranking_service.ranking_tab(scored.evaluation_id)
    ranks = [row.rank for row in view.rows]
    assert min(ranks) == 1
    if len(set(ranks)) == 1:
        assert view.verdict_headline.startswith("Two models are tied")


@pytest.mark.asyncio
async def test_the_verdict_is_composed_never_authored(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    view = await ranking_service.ranking_tab(scored.evaluation_id)
    assert view.verdict_headline
    if len({row.rank for row in view.rows}) == 1:
        assert "does not separate them" in view.verdict_headline


@pytest.mark.asyncio
async def test_the_presence_rate_takes_no_part_in_the_ranking(
    ranking_service: RankingService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**SD20, asserted as a negative.**

    §11.2 is unambiguous that presence has no independent gold label, and a
    model that flags everything present maximises the rate. It is reported
    beside latency and VRAM and must not move the ranking — so change every
    stored presence rate and assert the ranks and macros do not budge.
    """
    from sqlalchemy import update

    from ra2.domain.scoring import ScoreMetric
    from ra2.persistence.models import Score

    before = await ranking_service.ranking_tab(scored.evaluation_id)
    async with db_session_factory() as session:
        await session.execute(
            update(Score).where(Score.metric == ScoreMetric.PRESENCE_RATE).values(value=0.0)
        )
        await session.commit()
    after = await ranking_service.ranking_tab(scored.evaluation_id)

    assert [(r.model_id, r.rank) for r in before.rows] == [(r.model_id, r.rank) for r in after.rows]
    assert [r.macro_f1 for r in before.rows] == [r.macro_f1 for r in after.rows]
    assert [r.presence_rate for r in after.rows] != [r.presence_rate for r in before.rows]


@pytest.mark.asyncio
async def test_latency_and_tokens_are_reported(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    """Reported, never scored — the design's own rule 4."""
    view = await ranking_service.ranking_tab(scored.evaluation_id)
    for row in view.rows:
        assert row.median_latency_ms > 0
        assert row.prompt_tokens > 0


@pytest.mark.asyncio
async def test_ranking_reports_time_per_record_and_parallel_calls(
    ranking_service: RankingService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**SD38.** One run at 4 calls in flight, the rest at 1.

    Time per record is `mean latency ÷ parallel calls` (Little's law), read
    off the same rows as the median, and like the other reported columns it
    doesn't move the ranking. The expectation is computed here from the
    stored latencies, not copied from the service.
    """
    import statistics

    from sqlalchemy import select, update

    from ra2.persistence.models import Extraction, Run

    before = await ranking_service.ranking_tab(scored.evaluation_id)
    parallel = before.rows[0].model_id
    async with db_session_factory() as session:
        await session.execute(update(Run).where(Run.id == parallel).values(llm_parallel_calls=4))
        await session.commit()
        latencies = {
            row.model_id: [
                value
                for value in (
                    await session.scalars(
                        select(Extraction.latency_ms).where(Extraction.run_id == row.model_id)
                    )
                )
                if value is not None
            ]
            for row in before.rows
        }
    after = await ranking_service.ranking_tab(scored.evaluation_id)

    for row in after.rows:
        calls = 4 if row.model_id == parallel else 1
        assert row.parallel_calls == calls
        assert row.ms_per_record == round(statistics.fmean(latencies[row.model_id]) / calls)
    assert [(r.model_id, r.rank) for r in before.rows] == [(r.model_id, r.rank) for r in after.rows]
    # The median is what the ×N mark qualifies; it is reported as measured.
    assert [r.median_latency_ms for r in before.rows] == [r.median_latency_ms for r in after.rows]


@pytest.mark.asyncio
async def test_an_unscoreable_run_returns_a_well_formed_nothing_scoreable_payload(
    ranking_service: RankingService,
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Never an empty list — that is what a UI renders as a blank table, and
    "no results" is a different fact from "not enough data for results"
    (§16.7)."""
    async with db_session_factory() as session:
        evaluation = await session.get(Evaluation, scored.evaluation_id)
        assert evaluation is not None
        evaluation.min_cell_count = 10_000
        await session.commit()

    view = await ranking_service.ranking_tab(scored.evaluation_id)
    assert view.rows == ()
    assert view.scored_feature_count == 0
    assert "could be scored" in view.verdict_headline
    assert "10000" in view.verdict_detail
