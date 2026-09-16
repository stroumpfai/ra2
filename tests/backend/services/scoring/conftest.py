"""Fixtures for the scoring pass (plan-phase-4.md §8, T1)."""

from collections.abc import AsyncIterator
from itertools import count

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.scoring_service import ScoringService


class SeededIds:
    """Deterministic mismatch ids, so a re-score is byte-comparable."""

    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"mismatch-{next(self._counter):04d}"


@pytest.fixture
def scoring_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: object,
) -> ScoringService:
    return ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=_NullRunner(),  # type: ignore[arg-type]
        clock=frozen_clock,  # type: ignore[arg-type]
        id_factory=SeededIds(),
    )


class _NullRunner:
    """The pass is driven directly in these tests. `submit` has its own test;
    everything else calls `score_run` so a failure is an assertion rather than
    a swallowed background exception."""

    def submit(self, name: str, work: object) -> str:  # pragma: no cover - unused
        raise AssertionError("these tests drive the pass directly")


@pytest.fixture
async def seeded(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ScoredCorpus]:
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=40)
        await session.commit()
    yield corpus
