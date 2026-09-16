"""`ScoringService.score_run` — the pass (sw-design.md §16.1).

The headline tests are the two that cost something if they are wrong: an
interrupted pass that resumes without redoing or skipping work, and a re-score
that preserves an analyst's tag.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ALL_EMPTY, RIGHT_OF_WAY, WEATHER, ScoredCorpus

from ra2.domain.extraction import RunStatus
from ra2.domain.scoring import ALL_LANGUAGES, ScoreMetric
from ra2.persistence.models import Mismatch, Run, Score
from ra2.persistence.repositories.score_repo import ScoreRepository
from ra2.services.errors import RunNotScoreableError
from ra2.services.scoring_service import ScoringService


@pytest.mark.asyncio
async def test_scoring_writes_rows_for_every_labelled_feature(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        scored = await ScoreRepository(session).scored_feature_ids(seeded.run_ids[0])
    # Four of the five features score. `NieGefuelltFeld` is `s04`: its column
    # is populated for nobody, so it has no labelled cases and produces no
    # rows at all — not a zero, not a suppressed cell (§8.6).
    assert seeded.feature_ids[ALL_EMPTY] not in scored
    assert seeded.feature_ids[WEATHER] in scored
    assert seeded.feature_ids["vehicles"] in scored


@pytest.mark.asyncio
async def test_an_all_empty_column_produces_no_score_rows_at_all(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**`s04`, the §8.6 rule at the service layer.**

    Not rows of zeros, and not a suppressed cell — suppression is about *too
    few* labelled cases, and this feature has none at all.
    """
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        rows = await session.execute(
            select(Score).where(
                Score.run_id == seeded.run_ids[0],
                Score.feature_id == seeded.feature_ids[ALL_EMPTY],
            )
        )
        assert list(rows.scalars()) == []


@pytest.mark.asyncio
async def test_a_sparse_feature_is_scored_with_its_own_small_n(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**`s01`.** `VortrittAusw` has 17 labelled cases of 40 records.

    It **is** scored — suppression is a read-time rule applied from the stored
    `n` (SD19), never a write-time filter. That is what lets the floor change
    without a re-score.
    """
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        rows = await session.execute(
            select(Score).where(
                Score.run_id == seeded.run_ids[0],
                Score.feature_id == seeded.feature_ids[RIGHT_OF_WAY],
                Score.language == ALL_LANGUAGES,
                Score.metric == ScoreMetric.F1,
            )
        )
        stored = rows.scalar_one()
    assert stored.n == 17


@pytest.mark.asyncio
async def test_the_all_languages_n_equals_the_sum_of_the_per_language_ns(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Built from one list rather than two queries, so they cannot disagree —
    and a disagreement is a difference nobody would see on the screen."""
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        rows = await session.execute(
            select(Score).where(
                Score.run_id == seeded.run_ids[0],
                Score.feature_id == seeded.feature_ids[WEATHER],
                Score.metric == ScoreMetric.RECALL,
            )
        )
        by_language = {row.language: row.n for row in rows.scalars()}
    assert set(by_language) == {ALL_LANGUAGES, "de", "fr"}
    assert by_language[ALL_LANGUAGES] == by_language["de"] + by_language["fr"]


@pytest.mark.asyncio
async def test_scoring_the_same_run_twice_is_byte_identical(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The inputs are immutable, so anything else is a bug (§16.6)."""
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        first = [
            (s.feature_id, s.language, s.metric, s.value, s.n)
            for s in await ScoreRepository(session).for_run(seeded.run_ids[0])
        ]
    await scoring_service.rescore_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        second = [
            (s.feature_id, s.language, s.metric, s.value, s.n)
            for s in await ScoreRepository(session).for_run(seeded.run_ids[0])
        ]
    assert first == second


@pytest.mark.asyncio
async def test_a_second_score_run_does_no_work_because_nothing_is_pending(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**Resume is implicit.** "The features of a run with no `score` rows are
    the work left" — so re-entering after an interruption scores only those,
    and re-entering after a complete pass scores nothing.

    There is deliberately no separate `resume` entry point: one that skipped
    the same query would be a second answer to "how far did it get" (§16.1).
    """
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        before = await ScoreRepository(session).scored_feature_ids(seeded.run_ids[0])
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        after = await ScoreRepository(session).scored_feature_ids(seeded.run_ids[0])
    assert before == after


@pytest.mark.asyncio
async def test_an_interrupted_pass_resumes_without_redoing_or_skipping(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The headline test** (§16.1).

    Kill the pass after two features, re-enter, and assert every labelled
    feature ends with exactly one complete set of rows and none was scored
    twice. The per-`(run, feature)` commit is what makes that true: an
    interrupted pass leaves whole features done and whole features absent,
    never a feature half-scored from two different reads of the corpus.
    """
    original = ScoringService._score_one_feature
    calls: list[str] = []

    async def explode_after_two(self, session, run_id, corpus_id, feature, languages):
        if len(calls) >= 2:
            raise RuntimeError("scoring interrupted")
        calls.append(feature.key)
        await original(self, session, run_id, corpus_id, feature, languages)

    monkeypatch.setattr(ScoringService, "_score_one_feature", explode_after_two)
    with pytest.raises(RuntimeError, match="interrupted"):
        await scoring_service.score_run(seeded.run_ids[0])

    async with db_session_factory() as session:
        partial = await ScoreRepository(session).scored_feature_ids(seeded.run_ids[0])
    assert len(partial) == 2, "two whole features committed, the third not at all"

    monkeypatch.setattr(ScoringService, "_score_one_feature", original)
    await scoring_service.score_run(seeded.run_ids[0])

    async with db_session_factory() as session:
        rows = await ScoreRepository(session).for_run(seeded.run_ids[0])
        complete = await ScoreRepository(session).scored_feature_ids(seeded.run_ids[0])
    assert complete >= partial, "finished work was not thrown away"
    # No feature scored twice: every (feature, language, metric) appears once,
    # which the composite primary key would not have caught on its own if the
    # pass had appended instead of replacing.
    keys = [(r.feature_id, r.language, r.metric) for r in rows]
    assert len(keys) == len(set(keys))


@pytest.mark.asyncio
async def test_a_rescore_preserves_an_analysts_tag(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SD21, from the service side. A re-score exists because the *scorer's*
    code can change; the analyst's judgement did not."""
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        stored = (
            (await session.execute(select(Mismatch).where(Mismatch.run_id == seeded.run_ids[0])))
            .scalars()
            .first()
        )
        assert stored is not None, "the fixture's wrong answers must produce mismatches"
        stored.analyst_tag = "structured_data_error"
        tagged_id = stored.id
        await session.commit()

    await scoring_service.rescore_run(seeded.run_ids[0])

    async with db_session_factory() as session:
        after = await session.get(Mismatch, tagged_id)
        assert after is not None, "the re-score deleted a tagged row"
        assert after.analyst_tag == "structured_data_error"


@pytest.mark.asyncio
async def test_every_wrong_outcome_produces_a_mismatch_row(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """mvp-spec.md §12: "Every `wrong` outcome produces a `mismatch` row".

    Phase 4 writes them and never reads them — the review view is F11 — which
    is exactly why they are written now: phase 5 becomes a view over data that
    already exists.
    """
    await scoring_service.score_run(seeded.run_ids[0])
    async with db_session_factory() as session:
        wrong = (
            await session.execute(
                select(Score).where(
                    Score.run_id == seeded.run_ids[0],
                    Score.feature_id == seeded.feature_ids[WEATHER],
                    Score.language == ALL_LANGUAGES,
                    Score.metric == ScoreMetric.WRONG,
                )
            )
        ).scalar_one()
        mismatches = (
            (
                await session.execute(
                    select(Mismatch).where(
                        Mismatch.run_id == seeded.run_ids[0],
                        Mismatch.feature_id == seeded.feature_ids[WEATHER],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(mismatches) == int(wrong.value)
    assert all(m.analyst_tag is None for m in mismatches)


@pytest.mark.asyncio
async def test_a_failed_run_is_never_scored(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A partial corpus produces real-looking numbers over an unstated
    denominator — the failure §11.4's floor guards against at the other end of
    the scale (§16.1)."""
    async with db_session_factory() as session:
        run = await session.get(Run, seeded.run_ids[0])
        assert run is not None
        run.status = RunStatus.FAILED
        await session.commit()

    with pytest.raises(RunNotScoreableError, match="failed"):
        await scoring_service.score_run(seeded.run_ids[0])

    async with db_session_factory() as session:
        assert await ScoreRepository(session).scored_feature_ids(seeded.run_ids[0]) == frozenset()


@pytest.mark.asyncio
async def test_an_interrupted_run_is_never_scored(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        run = await session.get(Run, seeded.run_ids[0])
        assert run is not None
        run.status = RunStatus.INTERRUPTED
        await session.commit()
    with pytest.raises(RunNotScoreableError, match="interrupted"):
        await scoring_service.score_run(seeded.run_ids[0])


@pytest.mark.asyncio
async def test_status_is_derived_from_committed_rows(
    scoring_service: ScoringService,
    seeded: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**No status column** (§16.1, F5). The count that answers "how far did
    it get" is the same one that answers "where does it resume"."""
    async with db_session_factory() as session:
        before = await scoring_service.status(session, seeded.run_ids[0])
    assert before.scored_features == 0
    assert before.labelled_features == 5

    await scoring_service.score_run(seeded.run_ids[0])

    async with db_session_factory() as session:
        after = await scoring_service.status(session, seeded.run_ids[0])
    assert after.scored_features == 4, "the all-empty feature produces no rows"
