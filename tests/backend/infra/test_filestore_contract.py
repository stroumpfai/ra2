"""The `FileStore` contract (sw-design.md §3, §6.1) — one test, both stores.

`UploadedFileStore` and `HostPathFileStore` must be indistinguishable to
everything downstream: same `list_files`/`read_bytes` results for the same
bytes on disk. Where they differ — one accepts writes, the other is
read-only — a second, still-shared assertion checks each in its own branch of
the *same* parametrised test, per plan-m0-m5.md's A4 exit criterion.

`asyncio_mode = "auto"` (pyproject.toml) runs every `async def test_*` here
without an explicit `@pytest.mark.asyncio`.
"""

import asyncio
import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from ra2.domain.ids import DeliveryId
from ra2.infra.filestore import (
    FileStore,
    FileStoreError,
    HostPathFileStore,
    ReadOnlyFileStoreError,
    UploadedFileStore,
)

pytestmark = pytest.mark.backend

DELIVERY_ID = DeliveryId("delivery-1")
SEEDED_NAME = "unfall_zh.csv"
SEEDED_BYTES = b"UnfallUID;Kanton\n1;ZH\n"


@dataclass(frozen=True, slots=True)
class Case:
    """One `FileStore` under test, already seeded with one known file."""

    store: FileStore
    delivery_id: DeliveryId
    read_only: bool


@pytest.fixture(params=["upload", "host_path"])
def case(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Case]:
    store: FileStore
    if request.param == "upload":
        upload_store = UploadedFileStore(tmp_path / "deliveries", max_bytes=10_000_000)
        # Seed through the store's own intake — that is the only way an
        # UploadedFileStore ever gets bytes onto disk.
        asyncio.run(upload_store.accept(DELIVERY_ID, SEEDED_NAME, io.BytesIO(SEEDED_BYTES)))
        store = upload_store
        yield Case(store=store, delivery_id=DELIVERY_ID, read_only=False)
    else:
        # A host-path delivery: the file is already sitting on disk, placed
        # there by the analyst, never by the store.
        host_dir = tmp_path / "host"
        host_dir.mkdir()
        (host_dir / SEEDED_NAME).write_bytes(SEEDED_BYTES)
        host_store = HostPathFileStore()
        host_store.bind(DELIVERY_ID, host_dir)
        store = host_store
        yield Case(store=store, delivery_id=DELIVERY_ID, read_only=True)


async def test_list_files_and_read_bytes_agree_regardless_of_intake(case: Case) -> None:
    """Nothing downstream can tell an upload from a host-path registration."""
    files = await case.store.list_files(case.delivery_id)

    assert len(files) == 1
    stored = files[0]
    assert stored.filename == SEEDED_NAME
    assert stored.relative_path == SEEDED_NAME
    assert stored.byte_size == len(SEEDED_BYTES)
    assert stored.sha256 == hashlib.sha256(SEEDED_BYTES).hexdigest()

    read_back = await case.store.read_bytes(case.delivery_id, stored.relative_path)
    assert read_back == SEEDED_BYTES


async def test_accept_and_remove_follow_the_read_only_split(case: Case) -> None:
    """`ReadOnlyFileStoreError` on a host-path store; real writes on an upload one."""
    if case.read_only:
        with pytest.raises(ReadOnlyFileStoreError):
            await case.store.accept(case.delivery_id, "extra.csv", io.BytesIO(b"x"))
        with pytest.raises(ReadOnlyFileStoreError):
            await case.store.remove(case.delivery_id, SEEDED_NAME)
        return

    extra_bytes = b"UnfallUID;Kanton\n2;BE\n"
    stored = await case.store.accept(case.delivery_id, "extra.csv", io.BytesIO(extra_bytes))
    assert stored.byte_size == len(extra_bytes)

    listed = {f.relative_path for f in await case.store.list_files(case.delivery_id)}
    assert listed == {SEEDED_NAME, "extra.csv"}

    await case.store.remove(case.delivery_id, "extra.csv")
    listed_after = {f.relative_path for f in await case.store.list_files(case.delivery_id)}
    assert listed_after == {SEEDED_NAME}


async def test_upload_store_rejects_a_file_over_the_byte_limit(tmp_path: Path) -> None:
    """The one behaviour that is only `UploadedFileStore`'s to have."""
    store = UploadedFileStore(tmp_path / "deliveries", max_bytes=4)
    with pytest.raises(FileStoreError):
        await store.accept(DELIVERY_ID, "too_big.csv", io.BytesIO(b"way too many bytes"))

    # Nothing partial is left behind for the next analyse to trip over.
    assert await store.list_files(DELIVERY_ID) == ()


async def test_host_path_store_raises_for_an_unbound_delivery() -> None:
    store = HostPathFileStore()
    with pytest.raises(FileStoreError):
        await store.list_files(DeliveryId("never-bound"))
