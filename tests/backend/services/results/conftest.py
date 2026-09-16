"""Fixtures for the Results read models (plan-phase-4.md §8, T2/T3).

Both read services build against **scored** rows, so the fixture runs T1 once
and hands the tests a database that already has them — the shape Wave 2's three
agents were meant to work from in parallel.
"""

from collections.abc import AsyncIterator
from itertools import count

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.ranking_service import RankingService
from ra2.services.results_service import ResultsService
from ra2.services.scoring_service import ScoringService


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"mismatch-{next(self._counter):04d}"


@pytest.fixture
async def scored(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: object,
) -> AsyncIterator[ScoredCorpus]:
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=40)
        await session.commit()
    scoring = ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=None,  # type: ignore[arg-type]
        clock=frozen_clock,  # type: ignore[arg-type]
        id_factory=_Ids(),
    )
    for run_id in corpus.run_ids:
        await scoring.score_run(run_id)
    yield corpus


@pytest.fixture
def results_service(
    db_session_factory: async_sessionmaker[AsyncSession], frozen_clock: object
) -> ResultsService:
    scorer = ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=None,  # type: ignore[arg-type]
        clock=frozen_clock,  # type: ignore[arg-type]
        id_factory=_Ids(),
    )
    return ResultsService(session_factory=db_session_factory, scorer=scorer)


@pytest.fixture
def ranking_service(
    db_session_factory: async_sessionmaker[AsyncSession], frozen_clock: object
) -> RankingService:
    scorer = ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=None,  # type: ignore[arg-type]
        clock=frozen_clock,  # type: ignore[arg-type]
        id_factory=_Ids(),
    )
    return RankingService(session_factory=db_session_factory, scorer=scorer)
