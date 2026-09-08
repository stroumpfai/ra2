"""Round-trip tests for `DeliveryRepository` against a real temp-file SQLite
database (sw-design.md §11.2, plan-m0-m5.md A3 exit criteria)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.ids import DeliveryId, FileId
from ra2.persistence.models import Delivery, DeliveryFile
from ra2.persistence.repositories.delivery_repo import DeliveryRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


async def _seed_delivery_with_one_file(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[DeliveryId, FileId]:
    delivery_id = DeliveryId("delivery-1")
    file_id = FileId("file-1")
    async with session_factory() as session:
        repo = DeliveryRepository(session)
        delivery = Delivery(
            id=delivery_id,
            name="AG delivery",
            created_at=NOW,
            source_kind=SourceKind.UPLOAD,
            status=DeliveryStatus.REGISTERED,
        )
        await repo.add(delivery)
        file = DeliveryFile(
            id=file_id,
            delivery_id=delivery_id,
            filename="unfall_ag.txt",
            relative_path="unfall_ag.txt",
            byte_size=1024,
            sha256="a" * 64,
            file_kind=FileKind.UNFALL,
            selected=True,
        )
        session.add(file)
        await session.flush()
        await session.commit()
    return delivery_id, file_id


async def test_add_and_get_round_trips_a_delivery(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    delivery_id, _ = await _seed_delivery_with_one_file(db_session_factory)

    # A fresh session, so this reads back from the file, not from identity map.
    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        fetched = await repo.get(delivery_id)

    assert fetched is not None
    assert fetched.id == delivery_id
    assert fetched.name == "AG delivery"
    # `source_kind`/`status` are plain `String(16)` columns holding an enum's
    # *value* (M0-D7's pattern, applied uniformly by `type_annotation_map`) —
    # equal by value to the enum member, but not the same object once
    # reloaded from a fresh session.
    assert fetched.source_kind == SourceKind.UPLOAD
    assert fetched.status == DeliveryStatus.REGISTERED
    # SQLite's DATETIME storage format has no timezone offset, regardless of
    # `DateTime(timezone=True)` — a dialect limitation, not a repository bug.
    # Every timestamp in this app is UTC (`Clock` protocol), so a naive
    # round-trip value is still the right instant.
    assert fetched.created_at == NOW.replace(tzinfo=None)
    assert len(fetched.files) == 1
    assert fetched.files[0].filename == "unfall_ag.txt"


async def test_get_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        assert await repo.get(DeliveryId("does-not-exist")) is None


async def test_list_all_returns_every_delivery(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_delivery_with_one_file(db_session_factory)
    async with db_session_factory() as session:
        second = Delivery(
            id=DeliveryId("delivery-2"),
            name="BE delivery",
            created_at=NOW,
            source_kind=SourceKind.HOST_PATH,
            root_path="/data/be",
            status=DeliveryStatus.REGISTERED,
        )
        session.add(second)
        await session.commit()

    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        deliveries = await repo.list_all()

    assert {d.id for d in deliveries} == {DeliveryId("delivery-1"), DeliveryId("delivery-2")}


async def test_get_file_and_list_files_round_trip(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    delivery_id, file_id = await _seed_delivery_with_one_file(db_session_factory)

    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        file = await repo.get_file(file_id)
        assert file is not None
        assert file.filename == "unfall_ag.txt"
        assert file.file_kind == FileKind.UNFALL

        files = await repo.list_files(delivery_id)
        assert [f.id for f in files] == [file_id]


async def test_get_file_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        assert await repo.get_file(FileId("does-not-exist")) is None


async def test_deleting_a_delivery_cascades_to_its_files(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Not a repository method (repositories never delete a delivery), but the
    ORM `cascade="all, delete-orphan"` on `Delivery.files` is load-bearing for
    the re-parse/remove-file flows B1 builds in Wave 2 — worth proving here,
    once, while the models are fresh in this branch."""
    delivery_id, file_id = await _seed_delivery_with_one_file(db_session_factory)

    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        delivery = await repo.get(delivery_id)
        assert delivery is not None
        await session.delete(delivery)
        await session.commit()

    async with db_session_factory() as session:
        repo = DeliveryRepository(session)
        assert await repo.get(delivery_id) is None
        assert await repo.get_file(file_id) is None
