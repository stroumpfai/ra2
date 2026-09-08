"""Intake: register (both `FileStore` paths), add, remove (sw-design.md §6.1)."""

import io
from datetime import UTC

import pytest
from sqlalchemy import func, select

from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.ids import DeliveryId, FileId
from ra2.infra.filestore import ReadOnlyFileStoreError
from ra2.persistence.models import DeliveryFile
from ra2.services.errors import NotFoundError

pytestmark = pytest.mark.backend


async def test_register_upload_creates_an_empty_staging_area(delivery_service, clock):
    delivery_id = await delivery_service.register("BE 2025", source_kind=SourceKind.UPLOAD)

    view = await delivery_service.get(delivery_id)
    assert view.name == "BE 2025"
    assert view.source_kind is SourceKind.UPLOAD
    assert view.root_path is None
    assert view.status is DeliveryStatus.REGISTERED
    assert view.files == ()
    # SQLite has no offset storage, so a `DateTime(timezone=True)` column round
    # trips **naive** even though `Clock.now()` is UTC-aware. Asserted as-is
    # rather than papered over — see contracts/amendments/feat-m3-delivery-corpus.md.
    assert view.created_at.replace(tzinfo=UTC) == clock.now()


async def test_register_host_path_registers_the_files_in_place(delivery_service, hazards_dir):
    root = hazards_dir / "h10_count_mismatch"

    delivery_id = await delivery_service.register(
        "AG on disk", source_kind=SourceKind.HOST_PATH, root_path=root
    )

    view = await delivery_service.get(delivery_id)
    assert view.source_kind is SourceKind.HOST_PATH
    assert view.root_path == root.as_posix()
    # Registered, not copied: the rows exist and nothing was written into the
    # data dir (sw-design.md §6.1).
    assert [f.filename for f in view.files] == ["objekt.txt", "person.txt", "unfall.txt"]
    assert all(f.byte_size > 0 and len(f.sha256) == 64 for f in view.files)


async def test_register_rejects_a_host_path_delivery_with_no_root(delivery_service):
    with pytest.raises(ValueError, match="root_path"):
        await delivery_service.register("nowhere", source_kind=SourceKind.HOST_PATH)


async def test_register_rejects_a_root_path_on_an_upload(delivery_service, tmp_path):
    with pytest.raises(ValueError, match="no root_path"):
        await delivery_service.register("both", source_kind=SourceKind.UPLOAD, root_path=tmp_path)


async def test_add_file_streams_the_bytes_and_records_the_digest(
    delivery_service, upload_store, upload_delivery, hazard_bytes
):
    data = hazard_bytes("h10_count_mismatch", "unfall.txt")
    delivery_id = await upload_delivery("AG", [("unfall.txt", data)])

    view = await delivery_service.get(delivery_id)
    (row,) = view.files
    assert row.byte_size == len(data)
    assert await upload_store.read_bytes(delivery_id, row.relative_path) == data
    # Nothing is analysed yet: analyse is a separate phase (§6.2).
    assert row.file_kind is FileKind.UNKNOWN
    assert row.row_count is None
    assert row.analysed_at is None


async def test_add_file_refuses_a_host_path_delivery(delivery_service, hazards_dir):
    delivery_id = await delivery_service.register(
        "in place",
        source_kind=SourceKind.HOST_PATH,
        root_path=hazards_dir / "h08_all_empty_column",
    )
    with pytest.raises(ReadOnlyFileStoreError):
        await delivery_service.add_file(delivery_id, "unfall.txt", io.BytesIO(b"x"))


async def test_re_uploading_the_same_name_replaces_the_bytes_and_the_analysis(
    delivery_service, upload_store, upload_delivery, hazard_bytes
):
    first = hazard_bytes("h10_count_mismatch", "unfall.txt")
    delivery_id = await upload_delivery("AG", [("unfall.txt", first)])
    await delivery_service.analyse(delivery_id)
    before = (await delivery_service.get(delivery_id)).files[0]
    assert before.analysed_at is not None

    second = hazard_bytes("h08_all_empty_column", "unfall.txt")
    file_id = await delivery_service.add_file(delivery_id, "unfall.txt", io.BytesIO(second))

    assert file_id == before.file_id  # one row per relative_path, by constraint
    after = (await delivery_service.get(delivery_id)).files[0]
    assert after.byte_size == len(second)
    assert after.sha256 != before.sha256
    # The old analysis was about bytes that are no longer there.
    assert after.analysed_at is None
    assert after.file_kind is FileKind.UNKNOWN
    assert after.findings == ()
    assert await upload_store.read_bytes(delivery_id, after.relative_path) == second


async def test_remove_file_drops_the_row_and_the_uploaded_file(
    delivery_service, upload_store, upload_delivery, hazard_bytes, db_session_factory
):
    delivery_id = await upload_delivery(
        "AG",
        [
            ("unfall.txt", hazard_bytes("h10_count_mismatch", "unfall.txt")),
            ("objekt.txt", hazard_bytes("h10_count_mismatch", "objekt.txt")),
        ],
    )
    view = await delivery_service.get(delivery_id)
    doomed = next(f for f in view.files if f.filename == "objekt.txt")

    await delivery_service.remove_file(delivery_id, doomed.file_id)

    remaining = await delivery_service.get(delivery_id)
    assert [f.filename for f in remaining.files] == ["unfall.txt"]
    assert [f.filename for f in await upload_store.list_files(delivery_id)] == ["unfall.txt"]
    async with db_session_factory() as session:
        total = await session.scalar(
            select(func.count())
            .select_from(DeliveryFile)
            .where(DeliveryFile.delivery_id == delivery_id)
        )
    assert total == 1


async def test_remove_file_on_a_host_path_delivery_keeps_the_analysts_own_file(
    delivery_service, hazards_dir
):
    root = hazards_dir / "h10_count_mismatch"
    delivery_id = await delivery_service.register(
        "in place", source_kind=SourceKind.HOST_PATH, root_path=root
    )
    view = await delivery_service.get(delivery_id)
    doomed = next(f for f in view.files if f.filename == "person.txt")

    await delivery_service.remove_file(delivery_id, doomed.file_id)

    assert [f.filename for f in (await delivery_service.get(delivery_id)).files] == [
        "objekt.txt",
        "unfall.txt",
    ]
    # The file itself is untouched — it was never ours to delete.
    assert (root / "person.txt").is_file()


async def test_unknown_delivery_and_file_raise_not_found(
    delivery_service, upload_delivery, hazard_bytes
):
    with pytest.raises(NotFoundError) as missing_delivery:
        await delivery_service.get(DeliveryId("no-such-delivery"))
    assert missing_delivery.value.kind == "delivery"

    delivery_id = await upload_delivery(
        "AG", [("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt"))]
    )
    with pytest.raises(NotFoundError) as missing_file:
        await delivery_service.remove_file(delivery_id, FileId("no-such-file"))
    assert missing_file.value.kind == "delivery_file"


async def test_a_file_of_another_delivery_is_not_found_here(
    delivery_service, upload_delivery, hazard_bytes
):
    mine = await upload_delivery(
        "mine", [("unfall.txt", hazard_bytes("h08_all_empty_column", "unfall.txt"))]
    )
    theirs = await upload_delivery(
        "theirs", [("unfall.txt", hazard_bytes("h10_count_mismatch", "unfall.txt"))]
    )
    stranger = (await delivery_service.get(theirs)).files[0]

    with pytest.raises(NotFoundError):
        await delivery_service.set_selected(mine, stranger.file_id, selected=False)


async def test_list_deliveries_is_newest_first(delivery_service, clock):
    first = await delivery_service.register("older", source_kind=SourceKind.UPLOAD)
    clock.advance(seconds=60)
    second = await delivery_service.register("newer", source_kind=SourceKind.UPLOAD)

    listed = await delivery_service.list_deliveries()
    assert [d.delivery_id for d in listed] == [second, first]
