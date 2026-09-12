"""Fixtures for `CodelistService` (E1, Wave 2).

Same real-temp-file-SQLite idiom as `tests/backend/services/corpus/conftest.py`
and `tests/backend/services/census/test_census_service.py`: `db_session_factory`
comes from `tests/backend/conftest.py`'s `alembic upgrade head` chain, never
`Base.metadata.create_all()` (§12.10).

`coverage_counts()` (sw-design.md §14.2) reads the **live EAV cells**, not
`census_value` — so a fixture that exercises `coverage()`/`list_columns()`
needs both a materialised `census_column` row (for the enum type hint and
`distinct_count`) *and* the underlying `record`/`unfall_row` rows it was
computed from. `seed_enum_column` below builds both from the same value list,
so the two can never drift apart inside one test.
"""

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fixtures.factories import make_census_input, make_census_table_input, seed_corpus

from ra2.domain.ids import CorpusId, RecordId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.filestore import UploadedFileStore
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Record, UnfallRow
from ra2.persistence.session import create_session_factory
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.codelist_service import CodelistService

__all__ = [
    "clock",
    "codelist_service",
    "ids",
    "seed_enum_column",
    "upload_store",
]


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=1)


@pytest.fixture
def upload_store(run_upgrade_head: Settings) -> UploadedFileStore:
    return UploadedFileStore(
        run_upgrade_head.codelists_dir, max_bytes=run_upgrade_head.max_upload_bytes
    )


@pytest_asyncio.fixture
async def codelist_service(
    migrated_engine: AsyncEngine,
    upload_store: UploadedFileStore,
    clock: FrozenClock,
    ids: SeededFactory,
) -> CodelistService:
    return CodelistService(
        session_factory=create_session_factory(migrated_engine),
        upload_store=upload_store,
        clock=clock,
        ids=ids,
    )


@pytest.fixture
def codelists_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "fixtures" / "codelists" / "hazards"


@pytest.fixture
def codelist_bytes(codelists_dir: Path) -> Callable[[str], bytes]:
    def _read(hazard: str) -> bytes:
        return (codelists_dir / hazard / "codelist.json").read_bytes()

    return _read


@pytest.fixture
def seed_enum_column(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[None]]:
    """Seed one corpus with a materialised `*Ausw` (enum) census column, and
    the real `record`/`unfall_row` cells the column was computed from.

    One record per entry of `values`, in `unfall.<column_name>` — enough to
    exercise `coverage_counts()`'s live `GROUP BY value_raw` over the EAV
    cells, which is deliberately never read from `census_value` (sw-design.md
    §14.2).
    """

    async def _seed(
        corpus_id: str,
        *,
        column_name: str = "WetterAusw",
        values: Sequence[str],
    ) -> None:
        async with db_session_factory() as session:
            await seed_corpus(session, corpus_id, record_count=len(values))
            for index, value in enumerate(values):
                record_id = RecordId(f"{corpus_id}-r{index}")
                session.add(
                    Record(
                        id=record_id,
                        corpus_id=CorpusId(corpus_id),
                        unfall_uid=f"{corpus_id}-u{index}",
                        language="de",
                        language_confidence=1.0,
                    )
                )
                await session.flush()
                session.add(
                    UnfallRow(record_id=record_id, column_name=column_name, value_raw=value)
                )
            await session.flush()

            cells = [(column_name, value) for value in values]
            census_input = make_census_input(
                record_count=len(values),
                tables=[make_census_table_input("unfall", (column_name,), cells)],
            )
            materialiser = RelationalCensusMaterialiser(ids=SeededFactory(seed=2))
            await materialiser.materialise(session, CorpusId(corpus_id), census_input)
            await session.commit()

    return _seed
