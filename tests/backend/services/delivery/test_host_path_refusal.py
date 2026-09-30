"""A host-path registration outside the import root, or past a bound, is
refused with nothing written (`SD49`, risk A4).

The store does the refusing; the service turns it into a `ServiceError` and
guarantees no `delivery` or `delivery_file` row survives it.
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import SourceKind
from ra2.infra.config import Settings
from ra2.infra.filestore import HostPathFileStore
from ra2.infra.filestore import HostPathRefusedError as StoreRefused
from ra2.main import create_app
from ra2.persistence.models import Delivery, DeliveryFile
from ra2.services.delivery_service import DeliveryService
from ra2.services.errors import HostPathRefusedError

pytestmark = pytest.mark.backend


def _tree(root: Path, files: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(files):
        (root / f"f{index}.txt").write_bytes(b"UNFALLUID;TEXT\r\n")
    return root


@pytest.fixture
def constrained(
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
    upload_store: object,
    task_runner: object,
    clock: object,
    ids: object,
) -> tuple[DeliveryService, Path]:
    allowed = tmp_path / "import"
    service = DeliveryService(
        session_factory=db_session_factory,
        upload_store=upload_store,  # type: ignore[arg-type]
        host_path_store=HostPathFileStore(allowed_root=allowed, max_files=3),
        task_runner=task_runner,  # type: ignore[arg-type]
        clock=clock,  # type: ignore[arg-type]
        ids=ids,  # type: ignore[arg-type]
    )
    return service, allowed


async def _rows(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    async with session_factory() as session:
        deliveries = await session.scalar(select(func.count()).select_from(Delivery))
        files = await session.scalar(select(func.count()).select_from(DeliveryFile))
    return int(deliveries or 0), int(files or 0)


async def test_outside_the_import_root_is_refused_and_writes_nothing(
    constrained: tuple[DeliveryService, Path],
    tmp_path: Path,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service, _ = constrained

    with pytest.raises(HostPathRefusedError) as refused:
        await service.register(
            "home", source_kind=SourceKind.HOST_PATH, root_path=_tree(tmp_path / "home", 1)
        )

    assert refused.value.reason == StoreRefused.OUTSIDE_IMPORT_ROOT
    assert await _rows(db_session_factory) == (0, 0)


async def test_past_a_bound_is_refused_and_writes_nothing(
    constrained: tuple[DeliveryService, Path],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The walk runs inside the registration transaction, so a refusal
    halfway through rolls back the `delivery` row it had already added."""
    service, allowed = constrained

    with pytest.raises(HostPathRefusedError) as refused:
        await service.register(
            "share", source_kind=SourceKind.HOST_PATH, root_path=_tree(allowed / "share", 4)
        )

    assert refused.value.reason == StoreRefused.TOO_MANY_FILES
    assert await _rows(db_session_factory) == (0, 0)


async def test_inside_the_root_and_the_bounds_registers_as_before(
    constrained: tuple[DeliveryService, Path],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The positive control."""
    service, allowed = constrained

    await service.register(
        "delivery", source_kind=SourceKind.HOST_PATH, root_path=_tree(allowed / "d", 3)
    )

    assert await _rows(db_session_factory) == (1, 3)


def test_the_app_builds_its_store_from_settings(tmp_path: Path) -> None:
    """The wiring: `create_app()` hands `Settings`' root and bounds to the
    store it builds, so no caller has to remember to."""
    settings = Settings(
        data_dir=tmp_path / "data", import_max_files=7, import_max_gb=0.5, _env_file=None
    )
    app = create_app(settings=settings, mount_ui=False)
    store = app.state.services.delivery._host_path_store

    assert isinstance(store, HostPathFileStore)
    assert store._allowed_root == tmp_path / "data" / "import"
    assert store._max_files == 7
    assert store._max_bytes == 500_000_000


def test_the_import_root_defaults_under_the_data_dir_and_can_be_moved(tmp_path: Path) -> None:
    assert Settings(data_dir=tmp_path, _env_file=None).import_root_path == tmp_path / "import"
    moved = Settings(data_dir=tmp_path, import_root=tmp_path / "x", _env_file=None)
    assert moved.import_root_path == tmp_path / "x"
