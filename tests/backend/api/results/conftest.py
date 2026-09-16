"""Layer 2 fixtures for the Results routers (U1, U2, Wave 3).

A real `create_app`, a real migrated database and a **scored** corpus, so the
tests exercise the whole stack down to the `score` rows rather than a stub.
"""

from collections.abc import AsyncIterator
from itertools import count

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.scoring_service import ScoringService


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"api-mismatch-{next(self._counter):04d}"


@pytest.fixture
async def unscored(
    run_upgrade_head: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ScoredCorpus]:
    """A launched, finished evaluation that **nobody has scored**.

    The state §16.7 insists is a *state* and not an error.
    """
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=40)
        await session.commit()
    yield corpus


@pytest.fixture
async def scored(
    unscored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
) -> AsyncIterator[ScoredCorpus]:
    scoring = ScoringService(
        session_factory=db_session_factory,
        ground_truth=GroundTruthRepository(),
        task_runner=None,  # type: ignore[arg-type]
        clock=frozen_clock,
        id_factory=_Ids(),
    )
    for run_id in unscored.run_ids:
        await scoring.score_run(run_id)
    yield unscored


@pytest.fixture
async def api_client(
    run_upgrade_head: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
) -> AsyncIterator[AsyncClient]:
    """The real composition root, `mount_ui=False` — no NiceGUI, no network."""
    ids = _Ids()
    app = create_app(
        settings=run_upgrade_head,
        session_factory=db_session_factory,
        clock=frozen_clock,
        ids=ids,
        task_runner=InlineTaskRunner(ids),
        mount_ui=False,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
