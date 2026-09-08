"""Fixtures for `CorpusService` (B1, Wave 2).

Same shape as `../delivery/conftest.py`, which it deliberately overlaps:
`tests/backend/services/` has no shared conftest because B2 owns the sibling
directories in the same wave (plan-m0-m5.md §4).

The one substitute beyond the clock and the id factory is the
`CensusMaterialiser`. B2 implements the real one in parallel and B1 only ever
calls the protocol (E6), so the double here **records** what it was handed and
asserts nothing about the census itself — that is B2's exit criterion, not
B1's.
"""

import io
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import SourceKind
from ra2.domain.ids import CorpusId, DeliveryId, EvaluationId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.filestore import HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import SeededFactory
from ra2.infra.lingua_detector import LinguaDetector
from ra2.infra.tasks import InlineTaskRunner
from ra2.persistence.models import Evaluation
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.protocols import CensusInput

#: `tests/backend/services/corpus/` -> `tests/`
_TESTS_ROOT = Path(__file__).resolve().parents[3]
_HAZARDS = _TESTS_ROOT / "fixtures" / "deliveries" / "hazards"
_GOLDEN = _TESTS_ROOT / "fixtures" / "golden"

#: The delivery the golden import report is cut from: four committed hazard
#: files that together produce a report with something in every section — a
#: rejected wide row (h03), two count mismatches against the children delivered
#: with it (h10), a narrative whose key matches no surviving `unfall` row, and
#: French text with the cp1252-only characters already deleted (h09), which is
#: what makes the corpus canary say zero.
#:
#: Upload order is part of the fixture: `SeededFactory` hands out ids in call
#: order, so shuffling this list changes every `file_id` in the report.
GOLDEN_DELIVERY: tuple[tuple[str, str, str], ...] = (
    ("unfall.txt", "h03_stray_delimiter", "unfall.txt"),
    ("objekt.txt", "h10_count_mismatch", "objekt.txt"),
    ("person.txt", "h10_count_mismatch", "person.txt"),
    ("text.csv", "h09_fr_lossy", "text.csv"),
)

#: The instant every golden artefact is stamped with.
GOLDEN_SEED = 20260902


class RecordingMaterialiser:
    """A `CensusMaterialiser` that records rather than writes.

    B2 ships the real one; until then `create_app()` defaults to
    `_MissingCensusMaterialiser`, which raises. Injecting this keeps B1's
    freeze tests independent of B2's merge, which is the whole point of the
    seam (CONTRACTS.md, plan-m0-m5.md E6).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[AsyncSession, CorpusId, CensusInput]] = []

    async def materialise(
        self, session: AsyncSession, corpus_id: CorpusId, cells: CensusInput
    ) -> None:
        self.calls.append((session, corpus_id, cells))

    @property
    def only(self) -> tuple[AsyncSession, CorpusId, CensusInput]:
        assert len(self.calls) == 1, f"expected one materialise() call, got {len(self.calls)}"
        return self.calls[0]


@pytest.fixture
def hazards_dir() -> Path:
    return _HAZARDS


@pytest.fixture
def golden_dir() -> Path:
    """Committed golden artefacts (`tests/fixtures/golden/`)."""
    return _GOLDEN


@pytest.fixture
def hazard_bytes(hazards_dir: Path) -> Callable[[str, str], bytes]:
    def _read(hazard: str, filename: str) -> bytes:
        return (hazards_dir / hazard / filename).read_bytes()

    return _read


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=GOLDEN_SEED)


@pytest.fixture
def census_materialiser() -> RecordingMaterialiser:
    return RecordingMaterialiser()


@pytest.fixture
def language_detector() -> LinguaDetector:
    """The real detector. It is pure and deterministic, which is what the
    golden report needs; a stub would make the language counts a fiction."""
    return LinguaDetector()


@pytest.fixture
def task_runner(ids: SeededFactory) -> InlineTaskRunner:
    return InlineTaskRunner(ids)


@pytest.fixture
def upload_store(run_upgrade_head: Settings) -> UploadedFileStore:
    return UploadedFileStore(
        run_upgrade_head.deliveries_dir, max_bytes=run_upgrade_head.max_upload_bytes
    )


@pytest.fixture
def host_path_store() -> HostPathFileStore:
    return HostPathFileStore()


@pytest.fixture
def delivery_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    upload_store: UploadedFileStore,
    host_path_store: HostPathFileStore,
    task_runner: InlineTaskRunner,
    clock: FrozenClock,
    ids: SeededFactory,
) -> DeliveryService:
    return DeliveryService(
        session_factory=db_session_factory,
        upload_store=upload_store,
        host_path_store=host_path_store,
        task_runner=task_runner,
        clock=clock,
        ids=ids,
    )


@pytest.fixture
def corpus_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    census_materialiser: RecordingMaterialiser,
    language_detector: LinguaDetector,
    upload_store: UploadedFileStore,
    host_path_store: HostPathFileStore,
    task_runner: InlineTaskRunner,
    clock: FrozenClock,
    ids: SeededFactory,
    run_upgrade_head: Settings,
) -> CorpusService:
    return CorpusService(
        session_factory=db_session_factory,
        census_materialiser=census_materialiser,
        language_detector=language_detector,
        upload_store=upload_store,
        host_path_store=host_path_store,
        task_runner=task_runner,
        clock=clock,
        ids=ids,
        settings=run_upgrade_head,
    )


@pytest.fixture
def upload_delivery(
    delivery_service: DeliveryService,
) -> Callable[[str, Iterable[tuple[str, bytes]]], Awaitable[DeliveryId]]:
    """Register an upload delivery and stream files into it, in call order."""

    async def _register(name: str, files: Iterable[tuple[str, bytes]]) -> DeliveryId:
        delivery_id = await delivery_service.register(name, source_kind=SourceKind.UPLOAD)
        for filename, data in files:
            await delivery_service.add_file(delivery_id, filename, io.BytesIO(data))
        return delivery_id

    return _register


@pytest.fixture
def analysed_golden_delivery(
    delivery_service: DeliveryService,
    upload_delivery: Callable[[str, Iterable[tuple[str, bytes]]], Awaitable[DeliveryId]],
    hazard_bytes: Callable[[str, str], bytes],
) -> Callable[[], Awaitable[DeliveryId]]:
    """The golden delivery, uploaded and analysed. Returns its id."""

    async def _build() -> DeliveryId:
        delivery_id = await upload_delivery(
            "hazard delivery",
            [(name, hazard_bytes(hazard, source)) for name, hazard, source in GOLDEN_DELIVERY],
        )
        await delivery_service.analyse(delivery_id)
        return delivery_id

    return _build


@pytest.fixture
def seed_evaluation(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[EvaluationId]]:
    """Seed one `evaluation` row citing a corpus.

    Phase 1 never creates one; the table exists precisely so the delete guard
    is tested against a real row rather than a mock (M0-D1, sw-design.md §6.3).
    """

    async def _seed(corpus_id: CorpusId, name: str = "eval-1") -> EvaluationId:
        evaluation_id = EvaluationId(f"eval-{name}")
        async with db_session_factory() as session:
            session.add(Evaluation(id=evaluation_id, name=name, corpus_id=corpus_id))
            await session.commit()
        return evaluation_id

    return _seed
