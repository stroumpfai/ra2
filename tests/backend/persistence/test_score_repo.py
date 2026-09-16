"""`ScoreRepository` against a real temp-file SQLite database
(mvp-spec.md §5/§11, sw-design.md §16.1).

Two properties carry the scoring pass's restartability and are tested as such:
`write_feature` replaces one `(run, feature)`'s rows wholesale, and
`scored_feature_ids` is simultaneously the progress indicator and the resume
key — **there is no status column** for either to disagree with.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import LIGHT, WEATHER, seed_scored_corpus

from ra2.domain.scoring import ALL_LANGUAGES, ScoreMetric, ScoreRow
from ra2.persistence.models import Score
from ra2.persistence.repositories.score_repo import ScoreRepository


def row(
    metric: ScoreMetric, value: float, *, language: str = ALL_LANGUAGES, n: int = 40
) -> ScoreRow:
    return ScoreRow(
        language=language,
        metric=metric,
        value=value,
        n=n,
        ci_low=0.1 if metric not in {ScoreMetric.HIT} else None,
        ci_high=0.9 if metric not in {ScoreMetric.HIT} else None,
    )


@pytest.mark.asyncio
async def test_write_feature_round_trips(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = ScoreRepository(session)
        await repo.write_feature(
            seeded.run_ids[0],
            seeded.feature_ids[WEATHER],
            [row(ScoreMetric.F1, 0.842), row(ScoreMetric.HIT, 33.0)],
        )
        await session.commit()

    async with db_session_factory() as session:
        stored = await ScoreRepository(session).for_run(seeded.run_ids[0])
        by_metric = {s.metric: s for s in stored}
        assert by_metric[ScoreMetric.F1].value == pytest.approx(0.842)
        assert by_metric[ScoreMetric.F1].ci_low == pytest.approx(0.1)
        assert by_metric[ScoreMetric.HIT].value == 33.0
        assert by_metric[ScoreMetric.HIT].ci_low is None, "a count has no interval"


@pytest.mark.asyncio
async def test_writing_the_same_feature_again_replaces_its_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A `score` row is a pure function of immutable inputs, so replacement
    loses nothing — and a re-score that *appended* would double every count."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = ScoreRepository(session)
        feature_id = seeded.feature_ids[WEATHER]
        await repo.write_feature(seeded.run_ids[0], feature_id, [row(ScoreMetric.F1, 0.8)])
        await repo.write_feature(seeded.run_ids[0], feature_id, [row(ScoreMetric.F1, 0.9)])
        await session.commit()

    async with db_session_factory() as session:
        stored = await ScoreRepository(session).for_run(seeded.run_ids[0])
        assert len(stored) == 1
        assert stored[0].value == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_rewriting_one_feature_leaves_the_others_alone(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The transaction boundary is one `(run, feature)`. A rewrite that
    cleared the whole run would make a resumed pass redo finished work."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = ScoreRepository(session)
        await repo.write_feature(
            seeded.run_ids[0], seeded.feature_ids[WEATHER], [row(ScoreMetric.F1, 0.8)]
        )
        await repo.write_feature(
            seeded.run_ids[0], seeded.feature_ids[LIGHT], [row(ScoreMetric.F1, 0.9)]
        )
        await repo.write_feature(
            seeded.run_ids[0], seeded.feature_ids[WEATHER], [row(ScoreMetric.F1, 0.7)]
        )
        await session.commit()

    async with db_session_factory() as session:
        stored = {
            s.feature_id: s.value for s in await ScoreRepository(session).for_run(seeded.run_ids[0])
        }
        assert stored[seeded.feature_ids[WEATHER]] == pytest.approx(0.7)
        assert stored[seeded.feature_ids[LIGHT]] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_scored_feature_ids_is_the_progress_and_the_resume_key(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**There is no status column** (§16.1, F5). "How far did it get" and
    "where does it resume" are the same query, so they cannot disagree — the
    reasoning §15.3 used to refuse `records_done`, one level up."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = ScoreRepository(session)
        assert await repo.scored_feature_ids(seeded.run_ids[0]) == frozenset()
        await repo.write_feature(
            seeded.run_ids[0], seeded.feature_ids[WEATHER], [row(ScoreMetric.F1, 0.8)]
        )
        await session.commit()
        assert await repo.scored_feature_ids(seeded.run_ids[0]) == {seeded.feature_ids[WEATHER]}


@pytest.mark.asyncio
async def test_scores_are_scoped_to_their_run(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two models over one evaluation must not read each other's numbers."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        repo = ScoreRepository(session)
        await repo.write_feature(
            seeded.run_ids[0], seeded.feature_ids[WEATHER], [row(ScoreMetric.F1, 0.8)]
        )
        await repo.write_feature(
            seeded.run_ids[1], seeded.feature_ids[WEATHER], [row(ScoreMetric.F1, 0.6)]
        )
        await session.commit()
        assert await repo.scored_feature_ids(seeded.run_ids[1]) == {seeded.feature_ids[WEATHER]}
        assert [s.value for s in await repo.for_run(seeded.run_ids[1])] == [pytest.approx(0.6)]


@pytest.mark.asyncio
async def test_the_all_languages_row_and_a_per_language_row_coexist(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """**SD16.** `language` is part of the composite key and is `NOT NULL`
    with `'*'` for the all-languages row. Had it stayed nullable as
    mvp-spec.md §5 writes it, SQL would treat two NULLs as distinct and the
    key would permit exactly the duplicates it looks like it prevents.
    """
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        await ScoreRepository(session).write_feature(
            seeded.run_ids[0],
            seeded.feature_ids[WEATHER],
            [
                row(ScoreMetric.F1, 0.84, language=ALL_LANGUAGES),
                row(ScoreMetric.F1, 0.87, language="de"),
                row(ScoreMetric.F1, 0.77, language="fr"),
            ],
        )
        await session.commit()
        stored = {
            s.language: s.value for s in await ScoreRepository(session).for_run(seeded.run_ids[0])
        }
        assert set(stored) == {ALL_LANGUAGES, "de", "fr"}


@pytest.mark.asyncio
async def test_deleting_a_run_takes_its_scores_with_it(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Scores are derived: there is nothing to preserve once the run they
    describe is gone."""
    async with db_session_factory() as session:
        seeded = await seed_scored_corpus(session)
        await ScoreRepository(session).write_feature(
            seeded.run_ids[0], seeded.feature_ids[WEATHER], [row(ScoreMetric.F1, 0.8)]
        )
        await session.commit()
        run = await session.get(
            __import__("ra2.persistence.models", fromlist=["Run"]).Run, seeded.run_ids[0]
        )
        await session.delete(run)
        await session.commit()
        remaining = await session.execute(
            select(func.count()).select_from(Score).where(Score.run_id == seeded.run_ids[0])
        )
        assert remaining.scalar_one() == 0
