"""Fixtures for scrubbing at the service layer (sw-design.md §19).

The same shape as `../corpus/conftest.py`, which it overlaps deliberately:
`tests/backend/services/` has no shared conftest. Two differences: the census
materialiser is the **real** one, so the leak test can read every census row a
freeze writes; and the scrub fixtures come from `tests/fixtures/scrub/`.
"""

import importlib.util
import io
import sys
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import SourceKind
from ra2.domain.ids import DeliveryId
from ra2.domain.scrub import ListKind
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.filestore import HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import SeededFactory
from ra2.infra.lingua_detector import LinguaDetector
from ra2.infra.tasks import InlineTaskRunner
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.scrub_service import ScrubService

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
DELIVERY_HAZARDS = _FIXTURES / "deliveries" / "hazards"
SCRUB_HAZARDS = _FIXTURES / "scrub" / "hazards"

#: The fixture files, by the kind they are imported as.
FIXTURE_LISTS: tuple[tuple[ListKind, str], ...] = (
    (ListKind.REGEX, "s04_rules.toml"),
    (ListKind.FIRSTNAME, "s01_firstnames.txt"),
    (ListKind.LASTNAME, "s02_lastnames.txt"),
    (ListKind.WHITELIST, "s03_whitelist.txt"),
)


def generator() -> ModuleType:
    """`generate_hazards.py`, imported by path (`tests/fixtures/` is not a
    package): its row builders and `H18_PLANTED`."""
    path = _FIXTURES / "deliveries" / "generate_hazards.py"
    spec = importlib.util.spec_from_file_location("ra2_generate_hazards_scrub", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scrub_bytes(name: str) -> bytes:
    return (SCRUB_HAZARDS / name).read_bytes()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=20261018)


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
    clock: FrozenClock,
    ids: SeededFactory,
) -> DeliveryService:
    return DeliveryService(
        session_factory=db_session_factory,
        upload_store=upload_store,
        host_path_store=host_path_store,
        task_runner=InlineTaskRunner(ids),
        clock=clock,
        ids=ids,
    )


@pytest.fixture
def corpus_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    upload_store: UploadedFileStore,
    host_path_store: HostPathFileStore,
    clock: FrozenClock,
    ids: SeededFactory,
    run_upgrade_head: Settings,
) -> CorpusService:
    return CorpusService(
        session_factory=db_session_factory,
        census_materialiser=RelationalCensusMaterialiser(ids=ids),
        language_detector=LinguaDetector(),
        upload_store=upload_store,
        host_path_store=host_path_store,
        task_runner=InlineTaskRunner(ids),
        clock=clock,
        ids=ids,
        settings=run_upgrade_head,
    )


@pytest.fixture
def scrub_service(
    db_session_factory: async_sessionmaker[AsyncSession], clock: FrozenClock, ids: SeededFactory
) -> ScrubService:
    return ScrubService(session_factory=db_session_factory, clock=clock, ids=ids)


@pytest.fixture
def import_fixture_lists(scrub_service: ScrubService) -> Callable[[], Awaitable[None]]:
    """Import all four fixture files: the rule file, both name lists and the
    whitelist, in that order. Four versions; the last one active."""

    async def _import() -> None:
        for kind, name in FIXTURE_LISTS:
            await scrub_service.import_list(kind, name, scrub_bytes(name))

    return _import


@pytest.fixture
def analysed_delivery(
    delivery_service: DeliveryService,
) -> Callable[[str, Iterable[tuple[str, bytes]]], Awaitable[DeliveryId]]:
    """Register an upload delivery, add the files in call order, analyse it."""

    async def _build(name: str, files: Iterable[tuple[str, bytes]]) -> DeliveryId:
        delivery_id = await delivery_service.register(name, source_kind=SourceKind.UPLOAD)
        for filename, data in files:
            await delivery_service.add_file(delivery_id, filename, io.BytesIO(data))
        await delivery_service.analyse(delivery_id)
        return delivery_id

    return _build


@pytest.fixture
def h18_delivery(
    analysed_delivery: Callable[[str, Iterable[tuple[str, bytes]]], Awaitable[DeliveryId]],
) -> Callable[[], Awaitable[DeliveryId]]:
    async def _build() -> DeliveryId:
        directory = DELIVERY_HAZARDS / "h18_names_in_narrative"
        return await analysed_delivery(
            "h18",
            [(name, (directory / name).read_bytes()) for name in ("unfall.txt", "text.csv")],
        )

    return _build
