"""Layer 2 fixtures for `/api/v1/census/*`: a real app over a real migrated
SQLite database, driven through `httpx.ASGITransport` — no network (§12.9,
sw-design.md §11.2).

Reuses `tests/backend/conftest.py`'s `run_upgrade_head`/`db_session_factory`
(the real temp-file DB, migrated) and `tests/conftest.py`'s `frozen_clock`/
`seeded_ids`, rather than inventing a third way to build the app.
"""

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.conftest import FrozenClock, SeededFactory
from tests.fixtures.factories import seed_corpus

from ra2.domain.ids import CorpusId
from ra2.infra.config import Settings
from ra2.infra.idgen import SeededFactory as MaterialiserIdFactory
from ra2.main import create_app
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.protocols import CensusInput

__all__ = ["SeedCensusCorpus", "api_client", "seed_census_corpus"]

#: Seeds one `corpus` row plus its materialised census, given a corpus id, a
#: `CensusInput` and the record count it was computed over.
type SeedCensusCorpus = Callable[..., Awaitable[None]]


@pytest_asyncio.fixture
async def api_client(
    run_upgrade_head: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
    seeded_ids: SeededFactory,
) -> AsyncIterator[AsyncClient]:
    """An `AsyncClient` over a real app, real migrated DB, `mount_ui=False`."""
    app = create_app(
        settings=run_upgrade_head,
        session_factory=db_session_factory,
        clock=frozen_clock,
        ids=seeded_ids,
        mount_ui=False,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def seed_census_corpus(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> SeedCensusCorpus:
    """Seeds one `corpus` row plus its materialised census, the same way
    `tests/backend/services/census` does — so a corpus fetched through the
    HTTP API and one fetched through `CensusService` directly are asserted
    against the same stored numbers."""

    async def _seed(
        corpus_id: str,
        *,
        census_input: CensusInput,
        record_count: int,
        version: int = 1,
    ) -> None:
        materialiser = RelationalCensusMaterialiser(ids=MaterialiserIdFactory())
        async with db_session_factory() as session:
            await seed_corpus(session, corpus_id, record_count=record_count, version=version)
            await materialiser.materialise(session, CorpusId(corpus_id), census_input)
            await session.commit()

    return _seed
