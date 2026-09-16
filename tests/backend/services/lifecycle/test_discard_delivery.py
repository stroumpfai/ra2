"""Discarding a delivery: the rows, the bytes, and the one refusal
(plan-reset-and-discard.md §8, sw-design.md §18.2).

Two things here are easy to get wrong and are asserted rather than trusted:

1. **The bytes go, for an upload.** A delete that removed only the rows would
   leave a data directory that looks empty and is not — which matters more
   here than elsewhere, because these files are the sensitive delivery.
2. **A cited delivery is refused.** `corpus.delivery_id` is
   `ondelete="SET NULL"`, so the database will *not* refuse on its own: it
   would quietly null the provenance link. Only the service guard stops that,
   and this is the test that proves it is there.
"""

import io
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import SourceKind
from ra2.domain.ids import CorpusId, DeliveryId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.filestore import HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import SeededFactory
from ra2.infra.tasks import InlineTaskRunner
from ra2.persistence.models import Corpus, Delivery, DeliveryFile
from ra2.services.delivery_service import DeliveryService
from ra2.services.errors import DeliveryCitedError
from ra2.services.lifecycle_service import LifecycleService

pytestmark = pytest.mark.backend

_FILES = (("unfall.txt", b"UnfallUid|KantonAusw\r\n" + b"a" * 32 + b"|380\r\n"),)


@pytest.fixture
def delivery_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    backend_settings: Settings,
) -> DeliveryService:
    ids = SeededFactory(seed=20260916)
    return DeliveryService(
        session_factory=db_session_factory,
        upload_store=UploadedFileStore(
            backend_settings.deliveries_dir, max_bytes=backend_settings.max_upload_bytes
        ),
        host_path_store=HostPathFileStore(),
        task_runner=InlineTaskRunner(ids),
        clock=FrozenClock(),
        ids=ids,
    )


@pytest.fixture
async def uploaded(delivery_service: DeliveryService) -> AsyncIterator[DeliveryId]:
    delivery_id = await delivery_service.register("seed", source_kind=SourceKind.UPLOAD)
    for filename, data in _FILES:
        await delivery_service.add_file(delivery_id, filename, io.BytesIO(data))
    yield delivery_id


async def test_preview_counts_the_files(
    lifecycle_service: LifecycleService, uploaded: DeliveryId
) -> None:
    preview = await lifecycle_service.delivery_preview(uploaded)

    assert preview.kind == "delivery"
    assert preview.files == len(_FILES)
    assert preview.cited_by == 0
    assert preview.blocked is False
    # Nothing derived hangs off a delivery, so there is nothing to export —
    # which is the dialog's "Discard is enabled immediately" state (§18.5).
    assert preview.has_exportable is False


async def test_discard_removes_the_rows_and_the_bytes(
    lifecycle_service: LifecycleService,
    uploaded: DeliveryId,
    backend_settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stored = backend_settings.deliveries_dir / uploaded / _FILES[0][0]
    assert stored.is_file(), "the fixture must have written real bytes"

    await lifecycle_service.discard_delivery(uploaded)

    assert not stored.exists()
    async with db_session_factory() as session:
        assert await session.get(Delivery, uploaded) is None
        rows = (
            await session.scalars(
                select(DeliveryFile.id).where(DeliveryFile.delivery_id == uploaded)
            )
        ).all()
        assert list(rows) == []


async def test_a_cited_delivery_is_refused_and_keeps_its_link(
    lifecycle_service: LifecycleService,
    uploaded: DeliveryId,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Without the guard this passes silently and nulls `corpus.delivery_id` —
    which is exactly what `SET NULL` would do (SD4, §18.2)."""
    corpus_id = CorpusId("corpus-cites-delivery")
    async with db_session_factory() as session:
        session.add(
            Corpus(
                id=corpus_id,
                name="from that delivery",
                imported_at=FrozenClock().now(),
                version=1,
                source_file_manifest_json="[]",
                import_report_json="[]",
                record_count=1,
                is_dev_sized=True,
                cp1252_canary_count=0,
                delivery_id=uploaded,
            )
        )
        await session.commit()

    preview = await lifecycle_service.delivery_preview(uploaded)
    assert preview.cited_by == 1
    assert preview.blocked is True

    with pytest.raises(DeliveryCitedError):
        await lifecycle_service.discard_delivery(uploaded)

    async with db_session_factory() as session:
        corpus = await session.get(Corpus, corpus_id)
        assert corpus is not None
        assert corpus.delivery_id == uploaded


async def test_a_host_path_delivery_keeps_the_analysts_own_files(
    lifecycle_service: LifecycleService,
    delivery_service: DeliveryService,
    tmp_path: object,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`HostPathFileStore` registers files in place and refuses to remove
    them. The discard relies on that rather than working around it (§18.2)."""
    from pathlib import Path

    root = Path(str(tmp_path)) / "analysts-own"
    root.mkdir(parents=True, exist_ok=True)
    source = root / "unfall.txt"
    source.write_bytes(_FILES[0][1])

    delivery_id = await delivery_service.register(
        "in place", source_kind=SourceKind.HOST_PATH, root_path=root
    )
    await lifecycle_service.discard_delivery(delivery_id)

    assert source.is_file(), "a host-path delivery's files are not ours to delete"
    async with db_session_factory() as session:
        assert await session.get(Delivery, delivery_id) is None
