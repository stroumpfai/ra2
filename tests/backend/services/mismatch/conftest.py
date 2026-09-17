"""Fixtures for mismatch review (plan-phase-5.md §8, Y1).

The corpus is `scored_corpus`, **scored for real** rather than hand-written:
`mvp-spec.md` §12's rows come out of `s02`/`s03`'s wrong answers, and phase 5
is a view over data that already exists. A fixture that inserted `mismatch`
rows directly would test the view against a shape the scorer does not produce.

This is also the only place in the phase where a scoring service is
constructed. **`mismatch_service` never sees it** — it is here to *produce*
the rows the service reads, and the test that matters most in this directory
is the one proving no edge runs the other way (sw-design.md §17.3).
"""

from collections.abc import AsyncIterator
from itertools import count
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.infra.clock import FrozenClock
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.census_service import CensusService
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.export_service import ExportService
from ra2.services.mismatch_service import MismatchService
from ra2.services.scoring_service import ScoringService


class SeededIds:
    """Deterministic mismatch ids, so a re-score is byte-comparable and a
    sorted page is reproducible."""

    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"mismatch-{next(self._counter):04d}"


class _NullRunner:
    """The pass is driven directly here; nothing in this directory submits."""

    def submit(self, name: str, work: object) -> str:  # pragma: no cover - unused
        raise AssertionError("these tests drive the pass directly")


@pytest.fixture
def mismatch_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
) -> MismatchService:
    """A session factory and a clock, and **no scorer** — §17.3's absent edge
    in the wiring as well as in the imports."""
    return MismatchService(session_factory=db_session_factory, clock=frozen_clock)


@pytest.fixture
def scorer(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
) -> ScoringService:
    """Produces the rows under test. Handed to no service in this directory."""
    return ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=_NullRunner(),  # type: ignore[arg-type]
        clock=frozen_clock,
        id_factory=SeededIds(),
    )


@pytest.fixture
async def seeded(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ScoredCorpus]:
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=40)
        await session.commit()
    yield corpus


@pytest.fixture
async def scored(
    scorer: ScoringService,
    seeded: ScoredCorpus,
) -> ScoredCorpus:
    """Both runs scored, so every `wrong` outcome has its `mismatch` row and
    the one-run scope (`SD26`) has a second run to exclude."""
    for run_id in seeded.run_ids:
        await scorer.score_run(run_id)
    return seeded


@pytest.fixture
def export_service(frozen_clock: FrozenClock) -> ExportService:
    """`mismatches_csv` is a **pure writer**: it takes rows and returns bytes
    (`P4-D3`), so none of the three services on this constructor is reached.

    They are cast rather than built. Constructing a real `CorpusService` here
    would wire a file store, a census materialiser and a task runner for a
    function that touches none of them, and a reader of this fixture should not
    have to work out which of the four arguments matters. If a later change
    makes the exporter fetch something, these tests fail with an
    `AttributeError` on `None` — which is the right failure, loudly, at the
    line that reintroduced the dependency §7 rules out.
    """
    return ExportService(
        census_service=cast(CensusService, None),
        delivery_service=cast(DeliveryService, None),
        corpus_service=cast(CorpusService, None),
        clock=frozen_clock,
    )
