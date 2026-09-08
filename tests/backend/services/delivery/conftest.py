"""Fixtures for `DeliveryService` (B1, Wave 2).

Everything is real except the clock and the id factory: a real migrated
temp-file SQLite database (`tests/backend/conftest.py`), the real
`UploadedFileStore` over a temp directory, the real `InlineTaskRunner`. The two
substitutes are the two seams that would otherwise make a golden report move
between runs (sw-design.md §3).

`tests/backend/services/{delivery,corpus}/**` is B1's; `tests/backend/services/`
itself has no shared conftest because B2 owns the sibling directories in the
same wave (plan-m0-m5.md §4), so the small overlap with
`../corpus/conftest.py` is deliberate.

Everything shared is a **fixture**, never an importable helper: `tests/` is not
a package, so a sibling test module cannot import from a conftest by path.
"""

import io
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import SourceKind
from ra2.domain.ids import DeliveryId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.filestore import HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import SeededFactory
from ra2.infra.tasks import InlineTaskRunner
from ra2.services.delivery_service import DeliveryService

#: `tests/backend/services/delivery/` -> `tests/`
_TESTS_ROOT = Path(__file__).resolve().parents[3]
_HAZARDS = _TESTS_ROOT / "fixtures" / "deliveries" / "hazards"


@pytest.fixture
def hazards_dir() -> Path:
    """The twelve committed hazard fixtures (sw-design.md §11.4)."""
    return _HAZARDS


@pytest.fixture
def hazard_bytes(hazards_dir: Path) -> Callable[[str, str], bytes]:
    """One committed hazard file, verbatim. Binary — never a text-mode read."""

    def _read(hazard: str, filename: str) -> bytes:
        return (hazards_dir / hazard / filename).read_bytes()

    return _read


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=20260902)


@pytest.fixture
def upload_store(run_upgrade_head: Settings) -> UploadedFileStore:
    return UploadedFileStore(
        run_upgrade_head.deliveries_dir, max_bytes=run_upgrade_head.max_upload_bytes
    )


@pytest.fixture
def host_path_store() -> HostPathFileStore:
    return HostPathFileStore()


@pytest.fixture
def task_runner(ids: SeededFactory) -> InlineTaskRunner:
    """The synchronous runner: `submit()` has finished by the time it returns,
    so a backend test asserts on state rather than polling."""
    return InlineTaskRunner(ids)


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
def upload_delivery(
    delivery_service: DeliveryService,
) -> Callable[[str, Iterable[tuple[str, bytes]]], Awaitable[DeliveryId]]:
    """Register an upload delivery and stream files into it, in order.

    Order is the caller's, not a directory listing's: `SeededFactory` hands out
    ids in call order, so a golden test that shuffled the uploads would get
    different `file_id`s for the same delivery.
    """

    async def _register(name: str, files: Iterable[tuple[str, bytes]]) -> DeliveryId:
        delivery_id = await delivery_service.register(name, source_kind=SourceKind.UPLOAD)
        for filename, data in files:
            await delivery_service.add_file(delivery_id, filename, io.BytesIO(data))
        return delivery_id

    return _register
